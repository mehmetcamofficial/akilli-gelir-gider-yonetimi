import base64
import hashlib
import json
import mimetypes
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker

from database.db import engine
from database.models import (
    AuditLog, Booking, Collection, Document, DocumentReconciliation, ImportBatch,
    ReconciliationApproval, ReconciliationDifference, ReconciliationDocument,
    ReconciliationField, SupplierPayment, Tour, Transaction, Voucher,
)
from services.document_reconciliation_service import (
    AIExtractionError, DOCUMENT_TYPES, EXTRACTION_FIELDS, DocumentMatchingService,
    OpenRouterDocumentExtractor, ReconciliationEngine, ReconciliationExplanationService,
)
from services.drive_import_service import ColumnMappingService, ExcelFileReader, ValueNormalizationService
from services.google_drive_config import download_drive_file, initialize_drive_state
from utils.ui import page_header


Session = sessionmaker(bind=engine)
UPLOAD_TYPES = ["pdf", "jpg", "jpeg", "png", "xlsx", "xls", "csv"]
TYPE_LABELS = {
    "supplier_invoice": "Tedarikçi faturası", "restaurant_invoice": "Restoran faturası",
    "receipt": "Fiş", "pos_slip": "POS slipi", "voucher": "Voucher",
    "payment_receipt": "Ödeme makbuzu", "hotel_invoice": "Otel faturası",
    "transfer_invoice": "Transfer faturası", "guide_expense_document": "Rehber gider belgesi",
}
FIELD_LABELS = {
    "document_type": "Belge türü", "supplier_name": "Tedarikçi / restoran", "invoice_number": "Fatura numarası",
    "document_date": "Fatura tarihi", "voucher_number": "Voucher numarası", "booking_number": "Rezervasyon numarası",
    "tour_name": "Tur adı", "service_date": "Hizmet tarihi", "passenger_count": "Yolcu sayısı",
    "adult_count": "Yetişkin sayısı", "child_count": "Çocuk sayısı", "guide_count": "Rehber sayısı",
    "driver_count": "Şoför sayısı", "free_person_count": "Ücretsiz kişi hakkı", "currency": "Para birimi",
    "unit_price": "Birim fiyat", "subtotal": "Ara toplam", "tax_amount": "KDV", "tax_rate": "KDV oranı",
    "grand_total": "Genel toplam", "paid_amount": "Ödenen tutar", "remaining_amount": "Kalan tutar",
    "payment_method": "Ödeme yöntemi", "additional_charges": "Ek ücretler", "discounts": "İndirimler", "notes": "Notlar",
}
COMPARE_FIELDS = list(FIELD_LABELS)
DESTINATIONS = ["Faturalar", "Tedarikçi Ödemeleri", "Gelir ve Giderler", "Tahsilatlar", "Belge Arşivi", "Voucher Kayıtları", "Restoran Mutabakatları", "Otel Mutabakatları"]


def _secret_api_key():
    try: return st.secrets["OPENROUTER_API_KEY"]
    except Exception: return None


def _audit(session, event, entity_type=None, entity_id=None, details=None):
    session.add(AuditLog(event_type=event, entity_type=entity_type, entity_id=entity_id, details_json=json.dumps(details or {}, ensure_ascii=False, default=str)))
    session.commit()


def _mime(filename, supplied=None):
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf": return "application/pdf"
    if suffix in {".jpg", ".jpeg"}: return "image/jpeg"
    if suffix == ".png": return "image/png"
    return supplied or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _preview_file(file_bytes, filename, prefix):
    suffix = Path(filename).suffix.lower()
    st.caption(f"{filename} · {len(file_bytes):,} byte")
    zoom = st.slider("Yakınlaştırma", 75, 200, 100, 25, key=f"{prefix}_zoom")
    if suffix == ".pdf":
        try:
            import fitz
            document = fitz.open(stream=file_bytes, filetype="pdf")
            page_number = st.number_input("Sayfa", 1, len(document), 1, key=f"{prefix}_page")
            page = document[int(page_number) - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom / 100 * 1.3, zoom / 100 * 1.3), alpha=False)
            st.image(pixmap.tobytes("png"), use_container_width=True)
            st.caption(f"Sayfa {page_number}/{len(document)}")
        except Exception as exc:
            st.warning(f"PDF önizlemesi oluşturulamadı: {exc}")
    elif suffix in {".jpg", ".jpeg", ".png"}:
        st.image(file_bytes, width=min(1200, int(700 * zoom / 100)))
    elif suffix in {".xlsx", ".xls", ".csv"}:
        try:
            sheets = ExcelFileReader.sheet_names(file_bytes, filename)
            sheet = st.selectbox("Çalışma sayfası", sheets, key=f"{prefix}_sheet") if len(sheets) > 1 else sheets[0]
            frame, header = ExcelFileReader.analyze(file_bytes, filename, sheet)
            st.caption(f"Başlık satırı: {header + 1} · {len(frame)} satır")
            st.dataframe(frame.head(50), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.warning(f"Tablo önizlemesi oluşturulamadı: {exc}")


def _blank_extraction():
    result = {field: None for field in EXTRACTION_FIELDS}
    result["confidence"] = 0
    result["unreadable_fields"] = []
    return result


def _clear_editor_state():
    for prefix in ("rec_edit_left", "rec_edit_right"):
        for field in list(FIELD_LABELS) + ["type"]:
            st.session_state.pop(f"{prefix}_{field}", None)


def _extract_tabular(file_bytes, filename):
    frame, _ = ExcelFileReader.analyze(file_bytes, filename)
    mapping = ColumnMappingService.analyze(frame.columns)
    selected = {source: info["target"] for source, info in mapping.items() if info["target"] in EXTRACTION_FIELDS and info["confidence"] >= .72}
    row = ValueNormalizationService.row(frame.iloc[0], selected) if not frame.empty else {}
    result = _blank_extraction()
    result.update({key: value for key, value in row.items() if key in result})
    result["document_type"] = "supplier_invoice"
    result["confidence"] = .75 if selected else .25
    result["unreadable_fields"] = [field for field in FIELD_LABELS if result.get(field) is None]
    return result


def _extract_file(file_info):
    suffix = Path(file_info["name"]).suffix.lower()
    if suffix in {".xlsx", ".xls", ".csv"}:
        return _extract_tabular(file_info["bytes"], file_info["name"])
    extractor = OpenRouterDocumentExtractor(_secret_api_key())
    return extractor.extract(file_info["bytes"], file_info["name"], _mime(file_info["name"], file_info.get("type")))


def _agency_record_from_entity(kind, record, session):
    return DocumentMatchingService.agency_record({"entity_type": kind, "entity_id": record.id, "record": record, "score": 100}, session)


def _right_source_selector(session):
    source = st.radio("Kaynak", ["Dosya Yükle", "Rezervasyondan Seç", "Voucher’dan Seç", "Turdan Seç", "Ödeme Kaydından Seç", "Google Drive’dan Seç", "Excel Veri Aktarımı kayıtlarından seç"], key="rec_right_source")
    if source == "Dosya Yükle":
        upload = st.file_uploader("Acenta belgesini yükleyin", type=UPLOAD_TYPES, key="rec_right_upload")
        return ({"source": "upload", "name": upload.name, "type": upload.type, "bytes": upload.getvalue()} if upload else None), None
    if source == "Google Drive’dan Seç":
        initialize_drive_state()
        files = st.session_state.get("gdrive_files", [])
        if not files:
            st.info("Önce Ayarlar sayfasında Drive bağlantısını test edin ve dosyaları listeleyin.")
            return None, None
        index = st.selectbox("Drive dosyası", range(len(files)), format_func=lambda i: files[i].get("name", "Adsız"), key="rec_drive_file")
        item = files[index]
        if st.button("Drive Dosyasını Getir", key="rec_drive_download"):
            try:
                downloaded = download_drive_file(item["id"], item["mimeType"])
                name = f"{Path(item['name']).stem}.xlsx" if item["mimeType"] == "application/vnd.google-apps.spreadsheet" else item["name"]
                st.session_state.rec_drive_content = {"source": "drive", "name": name, "type": item["mimeType"], "bytes": downloaded.getvalue(), "entity_id": item["id"]}
            except Exception as exc: st.error(f"Drive dosyası alınamadı: {exc}")
        return st.session_state.get("rec_drive_content"), None
    model_map = {
        "Rezervasyondan Seç": (Booking, "booking", lambda r: f"{r.booking_number} · {r.passenger_count} kişi"),
        "Voucher’dan Seç": (Voucher, "voucher", lambda r: r.voucher_number or f"Voucher #{r.id}"),
        "Turdan Seç": (Tour, "tour", lambda r: f"{r.code} · {r.name}"),
        "Ödeme Kaydından Seç": (SupplierPayment, "supplier_payment", lambda r: f"{r.invoice_reference or 'Ödeme'} · {r.total_debt} {r.currency}"),
        "Excel Veri Aktarımı kayıtlarından seç": (ImportBatch, "import_batch", lambda r: f"#{r.id} · {r.filename} · {r.dataset_type}"),
    }
    model, kind, label = model_map[source]
    records = session.query(model).order_by(model.id.desc()).limit(200).all()
    if not records:
        st.info("Bu kaynakta seçilebilecek kayıt bulunamadı.")
        return None, None
    selected = st.selectbox("Acenta kaydı", records, format_func=label, key=f"rec_entity_{kind}")
    if kind == "import_batch":
        data = _blank_extraction(); data["notes"] = selected.result_json; data["confidence"] = 1
    else:
        data = _agency_record_from_entity(kind, selected, session)
    return {"source": "database", "name": label(selected), "entity_type": kind, "entity_id": selected.id}, data


def _manual_editor(prefix, title, initial):
    with st.expander(title, expanded=True):
        values = dict(initial or _blank_extraction())
        c1, c2, c3 = st.columns(3)
        values["document_type"] = c1.selectbox("Belge türü", DOCUMENT_TYPES, index=DOCUMENT_TYPES.index(values.get("document_type")) if values.get("document_type") in DOCUMENT_TYPES else 0, format_func=lambda x: TYPE_LABELS[x], key=f"{prefix}_type")
        for index, field in enumerate([f for f in FIELD_LABELS if f != "document_type"]):
            container = [c1, c2, c3][index % 3]
            current = values.get(field)
            if field in {"passenger_count", "adult_count", "child_count", "guide_count", "driver_count", "free_person_count"}:
                values[field] = container.number_input(FIELD_LABELS[field], min_value=0, value=int(current or 0), key=f"{prefix}_{field}")
            elif field in {"unit_price", "subtotal", "tax_amount", "tax_rate", "grand_total", "paid_amount", "remaining_amount", "additional_charges", "discounts"}:
                values[field] = container.number_input(FIELD_LABELS[field], value=float(current or 0), key=f"{prefix}_{field}")
            elif field == "currency":
                currencies = ["TRY", "EUR", "USD", "GBP", "Diğer"]
                values[field] = container.selectbox(FIELD_LABELS[field], currencies, index=currencies.index(current) if current in currencies else 0, key=f"{prefix}_{field}")
            else:
                values[field] = container.text_input(FIELD_LABELS[field], value=str(current or ""), key=f"{prefix}_{field}") or None
        values["confidence"] = float(initial.get("confidence") or 1) if initial else 1
        values["unreadable_fields"] = initial.get("unreadable_fields", []) if initial else []
        return values


def _field_status(field, left, right, differences, unreadable, overall_status):
    if field in unreadable or left in (None, ""):
        return "Okunamadı", "gray"
    difference = next((item for item in differences if item["field"] == field), None)
    if difference:
        if overall_status == "Küçük Fark Var":
            return "Küçük Fark", "yellow"
        return ("Kritik Uyumsuzluk", "red") if difference["severity"] in {"yüksek", "kritik"} else ("Kontrol Gerekli", "yellow")
    if right in (None, ""):
        return "Kayıt Bulunamadı", "gray"
    return "Eşleşti", "green"


def _comparison_frame(left, right, result):
    rows = []
    unreadable = set(left.get("unreadable_fields") or []) | set(right.get("unreadable_fields") or [])
    for field in COMPARE_FIELDS:
        lv, rv = left.get(field), right.get(field)
        status, color = _field_status(field, lv, rv, result["field_differences"], unreadable, result["status"])
        try: difference = float(lv) - float(rv) if lv not in (None, "") and rv not in (None, "") else "—"
        except (TypeError, ValueError): difference = "0" if str(lv).strip().casefold() == str(rv).strip().casefold() else "Farklı"
        rows.append({"Kontrol Alanı": FIELD_LABELS[field], "Karşıdan Gelen Belge": lv, "Acenta Kaydı": rv, "Fark": difference, "Durum": status, "Açıklama": next((x["label"] for x in result["field_differences"] if x["field"] == field), "Tolerans içinde" if color == "green" else "Alan kontrol edilmeli")})
    return pd.DataFrame(rows)


def _styled_comparison(frame):
    colors = {"Eşleşti": "background-color:#d1fae5", "Küçük Fark": "background-color:#fef3c7", "Kontrol Gerekli": "background-color:#fef3c7", "Kritik Uyumsuzluk": "background-color:#fee2e2", "Okunamadı": "background-color:#e5e7eb", "Kayıt Bulunamadı": "background-color:#e5e7eb"}
    return frame.style.apply(lambda row: [colors.get(row["Durum"], "") for _ in row], axis=1)


def _save_document(session, info):
    if not info or not info.get("bytes"): return None, None
    digest = hashlib.sha256(info["bytes"]).hexdigest()
    document = session.query(Document).filter(Document.file_hash == digest).first()
    if not document:
        document = Document(original_filename=info["name"], file_type=_mime(info["name"], info.get("type")), file_hash=digest, file_size=len(info["bytes"]))
        session.add(document); session.flush()
    return document, digest


def _persist(session, left_info, right_info, left, right, result, action, destination, note):
    left_document, left_hash = _save_document(session, left_info)
    right_document, right_hash = _save_document(session, right_info)
    reconciliation = DocumentReconciliation(document_id=left_document.id if left_document else None, document_hash=left_hash or hashlib.sha256(json.dumps(left, default=str).encode()).hexdigest(), extracted_json=json.dumps({"incoming": left, "agency": right}, ensure_ascii=False, default=str), matched_entity_type=right_info.get("entity_type") if right_info else result.get("matched_entity_type"), matched_entity_id=right_info.get("entity_id") if right_info else result.get("matched_entity_id"), status=result["status"], severity=result["severity"], differences_json=json.dumps(result["field_differences"], ensure_ascii=False, default=str), expected_total=result.get("expected_total"), document_total=result.get("document_total"), difference_amount=result.get("difference_amount"), difference_percentage=result.get("difference_percentage"), recommended_action=result.get("recommended_action"), user_action=action, user_note=note, reviewed_at=datetime.utcnow())
    session.add(reconciliation); session.flush()
    for side, info, document, digest, extracted in (("incoming", left_info, left_document, left_hash, left), ("agency", right_info, right_document, right_hash, right)):
        session.add(ReconciliationDocument(reconciliation_id=reconciliation.id, side=side, document_id=document.id if document else None, source_type=(info or {}).get("source", "manual"), source_entity_type=(info or {}).get("entity_type"), source_entity_id=(info or {}).get("entity_id"), filename=(info or {}).get("name"), file_hash=digest, content_base64=base64.b64encode(info["bytes"]).decode() if info and info.get("bytes") else None, extracted_json=json.dumps(extracted, ensure_ascii=False, default=str)))
    comparison = _comparison_frame(left, right, result)
    for row in comparison.to_dict("records"):
        session.add(ReconciliationField(reconciliation_id=reconciliation.id, field_name=row["Kontrol Alanı"], incoming_value=str(row["Karşıdan Gelen Belge"] or ""), agency_value=str(row["Acenta Kaydı"] or ""), status=row["Durum"], explanation=row["Açıklama"]))
    for item in result["field_differences"]:
        session.add(ReconciliationDifference(reconciliation_id=reconciliation.id, field_name=item["field"], incoming_value=str(item["document"]), agency_value=str(item["agency"]), difference_value=None, severity=item["severity"], explanation=item["label"]))
    session.add(ReconciliationApproval(reconciliation_id=reconciliation.id, action=action, destination=destination, approved_by=st.session_state.get("username") or "Streamlit kullanıcısı", note=note))
    if action == "approved" and destination in {"Faturalar", "Gelir ve Giderler"}:
        session.add(Transaction(transaction_type="expense", invoice_type="purchase", transaction_date=ValueNormalizationService.date(left.get("document_date")) or datetime.utcnow(), invoice_number=left.get("invoice_number"), party_name=left.get("supplier_name"), currency=left.get("currency") or "TRY", subtotal=left.get("subtotal") or 0, tax_total=left.get("tax_amount") or 0, grand_total=left.get("grand_total") or 0, paid_amount=left.get("paid_amount") or 0, remaining_amount=left.get("remaining_amount") or 0, payment_status="Ödendi" if not left.get("remaining_amount") else "Kısmen Ödendi"))
    session.add(AuditLog(event_type=f"reconciliation_{action}", entity_type="document_reconciliation", entity_id=reconciliation.id, details_json=json.dumps({"destination": destination}, ensure_ascii=False)))
    session.commit()
    return reconciliation.id


def render_document_reconciliation():
    page_header("Belge Mutabakatı", "Karşıdan gelen belgeyi acentanızın kendi kayıtlarıyla karşılaştırın, farkları inceleyin ve onaylayın.")
    st.progress(0.2 if not st.session_state.get("rec_result") else 0.8, text="1. Belgeyi yükle · 2. Acenta kaydını seç · 3. Analiz et · 4. Farkları kontrol et · 5. Onayla")
    session = Session()
    try:
        left_col, right_col = st.columns(2, gap="large")
        with left_col:
            st.subheader("Karşıdan Gelen Belge")
            st.caption("Restoran/otel/tedarikçi faturası, makbuz, POS slipi veya karşı taraf voucher’ı")
            upload = st.file_uploader("Belgeyi yükleyin", type=UPLOAD_TYPES, key="rec_left_upload")
            left_info = {"source": "upload", "name": upload.name, "type": upload.type, "bytes": upload.getvalue()} if upload else None
            if left_info: _preview_file(left_info["bytes"], left_info["name"], "rec_left")
        with right_col:
            st.subheader("Acenta Belgesi veya Kaydı")
            right_info, right_database = _right_source_selector(session)
            if right_info and right_info.get("bytes"): _preview_file(right_info["bytes"], right_info["name"], "rec_right")
            elif right_info: st.success(f"Seçilen kayıt: {right_info['name']}")

        analyze_disabled = not left_info or not right_info
        if st.button("Belgeleri Analiz Et", type="primary", use_container_width=True, disabled=analyze_disabled):
            try:
                with st.spinner("İki belge okunuyor ve deterministik kontroller hazırlanıyor..."):
                    left_extracted = _extract_file(left_info)
                    right_extracted = right_database or _extract_file(right_info)
                st.session_state.rec_left_extracted = left_extracted
                st.session_state.rec_right_extracted = right_extracted
                _clear_editor_state()
                st.session_state.rec_result = True
                _audit(session, "two_document_analysis_completed", details={"left": left_info["name"], "right": right_info["name"]})
            except AIExtractionError as exc:
                st.warning(f"AI kullanılamadı: {exc} Alanları manuel girerek aynı akışa devam edebilirsiniz.")
                st.session_state.rec_left_extracted = _blank_extraction()
                st.session_state.rec_right_extracted = right_database or _blank_extraction()
                _clear_editor_state()
                st.session_state.rec_result = True
            except Exception as exc:
                st.error(f"Belgeler analiz edilemedi: {exc}")

        if not st.session_state.get("rec_result"): return
        st.subheader("Çıkarılan Alanlar — İnsan Kontrolü")
        edit_left, edit_right = st.columns(2, gap="large")
        with edit_left: left = _manual_editor("rec_edit_left", "Karşıdan Gelen Belge Alanları", st.session_state.get("rec_left_extracted", {}))
        with edit_right: right = _manual_editor("rec_edit_right", "Acenta Belgesi / Kaydı Alanları", st.session_state.get("rec_right_extracted", {}))

        with st.expander("Karşılaştırma toleransları"):
            t1, t2, t3, t4 = st.columns(4)
            amount = t1.number_input("Tutar toleransı", 0.0, value=1.0)
            percentage = t2.number_input("Yüzde toleransı", 0.0, value=.5)
            passenger = t3.number_input("Kişi toleransı", 0, value=0)
            date = t4.number_input("Tarih toleransı (gün)", 0, value=1)
        duplicate_hash = bool(left_info and session.query(Document).filter(Document.file_hash == hashlib.sha256(left_info["bytes"]).hexdigest()).first())
        duplicate_invoice = bool(left.get("invoice_number") and session.query(Transaction).filter(Transaction.invoice_number == left["invoice_number"]).first())
        result = ReconciliationEngine(amount, percentage, passenger, date).reconcile(left, right, right_info.get("entity_type"), right_info.get("entity_id"), duplicate_hash, duplicate_invoice)
        st.session_state.rec_engine_result = result

        st.markdown("**Alan vurgulama:** 🟩 Yeşil: Eşleşti · 🟨 Sarı: Kontrol Edin · 🟥 Kırmızı: Kritik Fark · ⬜ Gri: Okunamadı")
        frame = _comparison_frame(left, right, result)
        st.dataframe(_styled_comparison(frame), use_container_width=True, hide_index=True)
        st.caption("Kaynak belgeler koordinat/bounding-box üretmediği için gerçek piksel vurgusu iddia edilmez; çıkarılmış alan kartları renklerle vurgulanır.")

        matched = int((frame["Durum"] == "Eşleşti").sum())
        critical = int((frame["Durum"] == "Kritik Uyumsuzluk").sum())
        summary = st.columns(6)
        for col, label, value in zip(summary, ["Genel Durum", "Eşleşen", "Farklı", "Kritik", "Beklenen", "Belge Toplamı"], [result["status"], matched, len(frame) - matched, critical, result["expected_total"], result["document_total"]]): col.metric(label, value if value is not None else "—")
        st.info(ReconciliationExplanationService.explain(result))
        st.write(f"**Toplam fark:** {result['difference_amount']} · **Önerilen işlem:** {result['recommended_action']}")
        if right_info.get("entity_type"):
            st.success(f"Bu belge büyük olasılıkla {right_info['name']} kaydıyla eşleşiyor. Öneri güveni: %100. Onay kullanıcıya aittir.")
        else:
            suggested_matches = DocumentMatchingService.find_matches(session, left)
            if suggested_matches:
                suggested = st.selectbox(
                    "İlişkili acenta kaydı önerileri",
                    suggested_matches,
                    format_func=lambda item: f"{item['entity_type']} #{item['entity_id']} · güven %{item['score']}",
                    key="rec_suggested_match",
                )
                right_info = dict(right_info)
                right_info["entity_type"] = suggested["entity_type"]
                right_info["entity_id"] = suggested["entity_id"]
                st.info(f"Bu belge büyük olasılıkla {suggested['entity_type']} #{suggested['entity_id']} kaydıyla eşleşiyor. Bu yalnızca öneridir; otomatik onaylanmaz.")

        st.subheader("Onay ve Kayıt")
        action = st.radio("İşlem", ["Onayla ve Kaydet", "Farklı Kayda Bağla", "Manuel Düzelt", "Tedarikçiye İtiraz Oluştur", "İncelemeye Gönder", "Belgeyi Reddet"], horizontal=True)
        destination = st.selectbox("Kayıt hedefi", DESTINATIONS)
        st.info(f"Bu belge **{destination}** sekmesine {'gider kaydı olarak ' if destination in {'Faturalar', 'Gelir ve Giderler'} else ''}kaydedilecek.")
        note = st.text_area("İnceleme notu")
        final_confirm = st.checkbox("İki belgeyi, karşılaştırma sonuçlarını ve seçilen kayıt hedefini kontrol ettim.")
        if action == "Tedarikçiye İtiraz Oluştur":
            draft = f"Sayın Tedarikçi,\n\n{left_info['name']} belgesinde şu farklar tespit edilmiştir:\n{ReconciliationExplanationService.explain(result)}\n\nKontrol ederek dönüş yapmanızı rica ederiz."
            st.download_button("İtiraz Taslağını İndir", draft.encode(), "tedarikci-itiraz.txt", "text/plain")
        if st.button("Seçilen İşlemi Uygula", type="primary", disabled=not final_confirm):
            action_code = {"Onayla ve Kaydet": "approved", "Farklı Kayda Bağla": "relink", "Manuel Düzelt": "manual_edit", "Tedarikçiye İtiraz Oluştur": "objection", "İncelemeye Gönder": "manual_review", "Belgeyi Reddet": "rejected"}[action]
            try:
                reconciliation_id = _persist(session, left_info, right_info, left, right, result, action_code, destination, note)
                st.success(f"İşlem kaydedildi. Mutabakat No: {reconciliation_id}")
            except Exception as exc:
                session.rollback(); st.error(f"Kayıt işlemi geri alındı: {exc}")
    finally:
        session.close()
