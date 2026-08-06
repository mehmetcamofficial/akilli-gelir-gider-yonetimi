import hashlib
import json
from datetime import datetime
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker

from database.db import engine
from database.models import AuditLog, Document, DocumentReconciliation, Transaction
from services.document_reconciliation_service import (
    AIExtractionError, DOCUMENT_TYPES, DocumentMatchingService,
    OpenRouterDocumentExtractor, ReconciliationEngine,
    ReconciliationExplanationService,
)
from utils.ui import page_header


TYPE_LABELS = {
    "supplier_invoice": "Tedarikçi faturası", "restaurant_invoice": "Restoran faturası",
    "receipt": "Fiş", "pos_slip": "POS slip", "voucher": "Voucher",
    "payment_receipt": "Ödeme makbuzu", "hotel_invoice": "Otel faturası",
    "transfer_invoice": "Transfer faturası", "guide_expense_document": "Rehber gider belgesi",
}


def _secret_api_key():
    try:
        return st.secrets["OPENROUTER_API_KEY"]
    except Exception:
        return None


def _audit(session, event_type, entity_type=None, entity_id=None, details=None):
    session.add(AuditLog(event_type=event_type, entity_type=entity_type, entity_id=entity_id, details_json=json.dumps(details or {}, ensure_ascii=False, default=str)))
    session.commit()


def _manual_fields(initial):
    with st.form("document_fields_form"):
        c1, c2, c3 = st.columns(3)
        doc_type = c1.selectbox("Belge türü", DOCUMENT_TYPES, index=DOCUMENT_TYPES.index(initial.get("document_type")) if initial.get("document_type") in DOCUMENT_TYPES else 0, format_func=lambda value: TYPE_LABELS[value])
        supplier_name = c2.text_input("Tedarikçi adı", value=initial.get("supplier_name") or "")
        invoice_number = c3.text_input("Fatura numarası", value=initial.get("invoice_number") or "")
        c1, c2, c3 = st.columns(3)
        document_date = c1.text_input("Belge tarihi (YYYY-AA-GG)", value=initial.get("document_date") or "")
        voucher_number = c2.text_input("Voucher numarası", value=initial.get("voucher_number") or "")
        booking_number = c3.text_input("Rezervasyon numarası", value=initial.get("booking_number") or "")
        c1, c2, c3 = st.columns(3)
        tour_name = c1.text_input("Tur adı", value=initial.get("tour_name") or "")
        service_date = c2.text_input("Hizmet tarihi (YYYY-AA-GG)", value=initial.get("service_date") or "")
        currency = c3.selectbox("Para birimi", ["TRY", "EUR", "USD", "GBP"], index=["TRY", "EUR", "USD", "GBP"].index(initial.get("currency")) if initial.get("currency") in ["TRY", "EUR", "USD", "GBP"] else 0)
        c1, c2, c3 = st.columns(3)
        passenger_count = c1.number_input("Yolcu sayısı", min_value=0, step=1, value=int(initial.get("passenger_count") or 0))
        adult_count = c2.number_input("Yetişkin sayısı", min_value=0, step=1, value=int(initial.get("adult_count") or 0))
        child_count = c3.number_input("Çocuk sayısı", min_value=0, step=1, value=int(initial.get("child_count") or 0))
        amounts = {}
        for row_fields in (("unit_price", "subtotal", "tax_amount"), ("grand_total", "paid_amount", "remaining_amount")):
            columns = st.columns(3)
            for column, field in zip(columns, row_fields):
                amounts[field] = column.number_input(field.replace("_", " ").title(), step=1.0, value=float(initial.get(field) or 0))
        saved = st.form_submit_button("Alanları Onayla ve Eşleştir", type="primary")
    if not saved:
        return None
    return {
        "document_type": doc_type, "supplier_name": supplier_name or None,
        "invoice_number": invoice_number or None, "document_date": document_date or None,
        "voucher_number": voucher_number or None, "booking_number": booking_number or None,
        "tour_name": tour_name or None, "service_date": service_date or None,
        "passenger_count": passenger_count, "adult_count": adult_count, "child_count": child_count,
        "currency": currency, **amounts, "confidence": float(initial.get("confidence") or 1),
        "unreadable_fields": initial.get("unreadable_fields") or [],
    }


def _persist_result(session, filename, mime_type, file_bytes, document_hash, extracted, result, action, note=""):
    document = session.query(Document).filter(Document.file_hash == document_hash).first()
    if not document:
        document = Document(original_filename=filename, stored_filename=None, file_path=None, file_type=mime_type, file_hash=document_hash, file_size=len(file_bytes))
        session.add(document); session.flush()
    reconciliation = DocumentReconciliation(
        document_id=document.id, document_hash=document_hash,
        extracted_json=json.dumps(extracted, ensure_ascii=False, default=str),
        matched_entity_type=result.get("matched_entity_type"), matched_entity_id=result.get("matched_entity_id"),
        status=result["status"], severity=result["severity"],
        differences_json=json.dumps(result["field_differences"], ensure_ascii=False, default=str),
        expected_total=result.get("expected_total"), document_total=result.get("document_total"),
        difference_amount=result.get("difference_amount"), difference_percentage=result.get("difference_percentage"),
        recommended_action=result.get("recommended_action"), user_action=action, user_note=note,
        reviewed_at=datetime.utcnow(),
    )
    session.add(reconciliation); session.commit(); session.refresh(reconciliation)
    return document, reconciliation


def render_document_reconciliation():
    page_header("Belge Mutabakatı", "Belgeleri AI destekli okuyun; eşleştirme ve mali kontrolleri deterministik kurallarla doğrulayın.")
    st.info("AI yalnızca alan çıkarır ve öneri sunar. Muhasebe kaydı ancak kullanıcı onayıyla oluşturulur veya değiştirilir.")
    uploaded = st.file_uploader("PDF, JPG, JPEG veya PNG yükleyin", type=["pdf", "jpg", "jpeg", "png"], key="reconciliation_upload")
    if not uploaded:
        return
    file_bytes = uploaded.getvalue()
    document_hash = hashlib.sha256(file_bytes).hexdigest()
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        duplicate = session.query(Document).filter(Document.file_hash == document_hash).first() is not None
        st.write(f"Belge özeti: **{uploaded.name}** • {len(file_bytes):,} byte")
        st.code(f"SHA-256: {document_hash}", language=None)
        if duplicate:
            st.error("Bu belge daha önce yüklenmiş. Mutabakat sonucu mükerrer belge olarak işaretlenecek.")
        if st.session_state.get("reconciliation_logged_hash") != document_hash:
            _audit(session, "document_uploaded", "document", details={"hash": document_hash, "filename": uploaded.name, "duplicate": duplicate})
            st.session_state.reconciliation_logged_hash = document_hash

        extract_col, manual_col = st.columns(2)
        if extract_col.button("AI ile Alanları Çıkar", type="primary"):
            try:
                extractor = OpenRouterDocumentExtractor(_secret_api_key())
                with st.spinner("Belge güvenli yapılandırılmış çıktı ile inceleniyor..."):
                    extracted = extractor.extract(file_bytes, uploaded.name, uploaded.type)
                st.session_state.reconciliation_extracted = extracted
                _audit(session, "ai_extraction_completed", "document", details={"hash": document_hash, "confidence": extracted["confidence"]})
            except AIExtractionError as exc:
                st.session_state.reconciliation_ai_error = str(exc)
                st.warning(str(exc))
        if manual_col.button("Manuel Alan Girişini Aç"):
            st.session_state.reconciliation_manual = True
        initial = st.session_state.get("reconciliation_extracted", {})
        if st.session_state.get("reconciliation_ai_error") or not _secret_api_key():
            st.warning("AI kullanılamıyor; aynı mutabakat akışına manuel alan girişiyle devam edebilirsiniz.")
            st.session_state.reconciliation_manual = True
        if initial and float(initial.get("confidence") or 0) < 0.60:
            st.warning("AI güven skoru düşük. Alanları özellikle kontrol edin.")
            st.session_state.reconciliation_manual = True
        if initial:
            st.subheader("AI Tarafından Çıkarılan Alanlar — Kullanıcı Onayı Gerekli")
            st.json(initial)
        if initial or st.session_state.get("reconciliation_manual"):
            confirmed = _manual_fields(initial)
            if confirmed:
                st.session_state.reconciliation_confirmed = confirmed

        extracted = st.session_state.get("reconciliation_confirmed")
        if not extracted:
            return
        matches = DocumentMatchingService.find_matches(session, extracted)
        options = list(range(len(matches)))
        selected_index = st.selectbox("Önerilen acente kaydı", options, format_func=lambda index: f"{matches[index]['entity_type']} #{matches[index]['entity_id']} • eşleşme {matches[index]['score']}" if matches else "Eşleşme yok", disabled=not matches) if matches else None
        selected = matches[selected_index] if selected_index is not None else None
        agency = DocumentMatchingService.agency_record(selected, session)
        st.subheader("Toleranslar")
        t1, t2, t3, t4 = st.columns(4)
        amount_tolerance = t1.number_input("Tutar toleransı", min_value=0.0, value=1.0)
        percentage_tolerance = t2.number_input("Yüzde toleransı", min_value=0.0, value=0.5)
        passenger_tolerance = t3.number_input("Yolcu toleransı", min_value=0, value=0)
        date_tolerance = t4.number_input("Tarih toleransı (gün)", min_value=0, value=1)
        duplicate_invoice = bool(
            extracted.get("invoice_number")
            and session.query(Transaction).filter(
                Transaction.invoice_number == extracted["invoice_number"]
            ).count() > 0
        )
        engine_result = ReconciliationEngine(amount_tolerance, percentage_tolerance, passenger_tolerance, date_tolerance).reconcile(
            extracted, agency, selected["entity_type"] if selected else None,
            selected["entity_id"] if selected else None, duplicate, duplicate_invoice,
        )
        _audit_key = f"{document_hash}:{json.dumps(engine_result, sort_keys=True, default=str)}"
        if st.session_state.get("reconciliation_result_audit") != _audit_key:
            _audit(session, "reconciliation_completed", selected["entity_type"] if selected else None, selected["entity_id"] if selected else None, {"status": engine_result["status"], "hash": document_hash})
            st.session_state.reconciliation_result_audit = _audit_key

        st.subheader(f"Sonuç: {engine_result['status']}")
        st.write(ReconciliationExplanationService.explain(engine_result))
        comparison = []
        for key in ("voucher_number", "booking_number", "supplier_name", "service_date", "passenger_count", "unit_price", "subtotal", "tax_amount", "grand_total", "currency", "paid_amount", "remaining_amount"):
            left, right = extracted.get(key), agency.get(key)
            comparison.append({"Alan": key, "Yüklenen Belge": left, "Acente Kaydı": right, "Fark": "—" if str(left) == str(right) else f"{left} → {right}"})
        st.dataframe(pd.DataFrame(comparison), width="stretch", hide_index=True)
        st.json(engine_result)
        note = st.text_area("İnceleme notu")
        a1, a2, a3 = st.columns(3)
        if a1.button("Doğrula ve Kaydet", type="primary"):
            document, rec = _persist_result(session, uploaded.name, uploaded.type, file_bytes, document_hash, extracted, engine_result, "approved", note)
            _audit(session, "user_approved", "document_reconciliation", rec.id, {"document_id": document.id})
            st.success("Mutabakat sonucu kaydedildi. Muhasebe kaydı otomatik değiştirilmedi.")
        if a2.button("İlgili Kaydı Değiştir", disabled=not selected):
            page_map = {"booking": "Rezervasyonlar", "voucher": "Rezervasyonlar", "tour": "Turlar ve Paketler", "supplier": "Tedarikçiler", "invoice": "Faturalar", "supplier_payment": "Tedarikçi Ödemeleri"}
            st.session_state.active_page = page_map.get(selected["entity_type"], "Kontrol Merkezi")
            _audit(session, "record_modification_requested", selected["entity_type"], selected["entity_id"], {"hash": document_hash})
            st.rerun()
        if a3.button("Manuel İncelemeye Gönder"):
            _, rec = _persist_result(session, uploaded.name, uploaded.type, file_bytes, document_hash, extracted, engine_result, "manual_review", note)
            _audit(session, "manual_review_requested", "document_reconciliation", rec.id)
            st.success("Belge manuel inceleme kuyruğuna gönderildi.")
        b1, b2 = st.columns(2)
        draft = f"Sayın Tedarikçi,\n\n{uploaded.name} belgesinde şu farklar tespit edilmiştir:\n{ReconciliationExplanationService.explain(engine_result)}\n\nKontrol ederek dönüş yapmanızı rica ederiz."
        b1.download_button("Tedarikçiye İtiraz Taslağı Oluştur", draft.encode("utf-8"), "tedarikci-itiraz-taslagi.txt", "text/plain")
        if b2.button("Belgeyi Reddet"):
            _, rec = _persist_result(session, uploaded.name, uploaded.type, file_bytes, document_hash, extracted, engine_result, "rejected", note)
            _audit(session, "user_rejected", "document_reconciliation", rec.id)
            st.error("Belge reddedildi ve denetim kaydı oluşturuldu.")
    finally:
        session.close()
