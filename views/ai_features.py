import json
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from database.db import engine
from database.models import (
    AIExtraction, AIExtractionField, AIFieldCorrection, AIRequest, AIUsageLog,
    ApprovalRequest, AuditLog, Document, DocumentConfidenceScore,
    DocumentReconciliation, ManagementCommentary, SupplierObjectionDraft,
    Transaction,
)
from services.accounting_automation_service import ApprovalWorkflowService, ReconciliationExportService
from services.ai_service import (
    AIModelConfigService, AIResponseError, AIUnavailableError,
    AccountingAssistantService, DocumentConfidenceService,
    DocumentExtractionService, DocumentPreprocessingService,
    ExtractionValidationService, ManagementInsightService, OpenRouterClient,
    SupplierObjectionService,
)
from services.storage_service import load_document_bytes, store_document_bytes
from utils.ui import page_header


Session = sessionmaker(bind=engine)


def _navigate(page):
    st.session_state.active_page = page; st.rerun()


def _usage_cards(session):
    now = datetime.utcnow(); today = now.replace(hour=0, minute=0, second=0, microsecond=0); month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today_count = session.query(AIUsageLog).filter(AIUsageLog.created_at >= today).count()
    month_rows = session.query(AIUsageLog).filter(AIUsageLog.created_at >= month).all()
    failed = sum(row.status != "Başarılı" for row in month_rows); cost = sum((Decimal(row.estimated_cost or 0) for row in month_rows), Decimal(0)); avg = round(sum(row.duration_ms or 0 for row in month_rows) / len(month_rows)) if month_rows else 0
    columns = st.columns(5)
    for column, label, value in zip(columns, ["Bugünkü AI İsteği", "Bu Ay AI İsteği", "Tahmini Maliyet", "Başarısız İstek", "Ortalama Yanıt"], [today_count, len(month_rows), f"${cost:.4f}", failed, f"{avg} ms"]): column.metric(label, value)
    config = AIModelConfigService.config()
    if today_count >= config["daily_warning"]: st.warning("Günlük AI kullanım uyarı sınırına ulaşıldı. Manuel iş akışları kullanılabilir.")
    if cost >= config["monthly_cost_warning"]: st.warning("Aylık tahmini AI maliyet uyarı sınırına ulaşıldı.")


def _field_rows(extraction, validation):
    checks = {item["field"]: item for item in validation["checks"]}
    rows = []
    for name, item in extraction["fields"].items():
        check = checks.get(name); confidence = float(item.get("confidence") or 0)
        status = check["status"] if check else "Güvenilir" if confidence >= .85 else "Kontrol Edin" if item.get("value") is not None else "Okunamadı"
        rows.append({"Alan": name, "AI Değeri": item.get("value"), "Güven": round(confidence * 100), "Sayfa": item.get("source_page"), "Kaynak": item.get("source_text"), "Durum": status, "Açıklama": check["message"] if check else ""})
    return rows


def render_ai_document_review():
    page_header("AI Belge İnceleme", "Belgeyi okutun, deterministik kontrolleri görün ve alanları insan onayıyla kaydedin.")
    session = Session()
    try:
        _usage_cards(session)
        source = st.radio("Belge kaynağı", ["Bilgisayardan Yükle", "Belge Arşivinden Seç"], horizontal=True)
        content = filename = mime = document = None
        if source == "Bilgisayardan Yükle":
            uploaded = st.file_uploader("PDF veya görsel belge", type=["pdf", "jpg", "jpeg", "png"], key="ai_document_upload")
            if uploaded:
                content, filename, mime = uploaded.getvalue(), uploaded.name, uploaded.type
                st.session_state.ai_pending_document = {"content": content, "filename": filename, "mime": mime}
            elif st.session_state.get("ai_pending_document"):
                pending = st.session_state.ai_pending_document; content, filename, mime = pending["content"], pending["filename"], pending["mime"]
        else:
            documents = session.query(Document).order_by(Document.uploaded_at.desc()).all()
            if documents:
                document = st.selectbox("Arşiv belgesi", documents, format_func=lambda item: f"#{item.id} · {item.original_filename}")
                try: content, filename, mime = load_document_bytes(document), document.original_filename, document.file_type
                except Exception as exc: st.warning(f"Belge alınamadı: {exc}")
        if content:
            st.caption(f"{filename} · {len(content):,} byte · SHA-256: {__import__('hashlib').sha256(content).hexdigest()}")
            if mime == "application/pdf" and hasattr(st, "pdf"): st.pdf(content)
            elif str(mime).startswith("image/"): st.image(content, width=700)
        analyze = st.button("Belgeyi Analiz Et", type="primary", disabled=not content)
        if analyze:
            try:
                preprocessing = DocumentPreprocessingService.preprocess(content, filename)
                if document is None:
                    document, duplicate = store_document_bytes(content, filename, mime, session)
                else: duplicate = session.query(Document).filter(Document.file_hash == document.file_hash, Document.id != document.id).first() is not None
                client = OpenRouterClient(session=session)
                extraction, request_id = DocumentExtractionService.extract(client, preprocessing)
                values = ExtractionValidationService.values(extraction)
                internal_match = bool((values.get("invoice_number") and session.query(Transaction).filter(Transaction.invoice_number == values["invoice_number"]).first()) or values.get("voucher_number") or values.get("booking_number"))
                validation = ExtractionValidationService.validate(extraction, duplicate, internal_match)
                confidence = DocumentConfidenceService.calculate(extraction, validation, preprocessing)
                st.session_state.ai_review = {"document_id": document.id, "extraction": extraction, "validation": validation, "confidence": confidence, "request_id": request_id, "warnings": preprocessing["warnings"]}
                session.add(AuditLog(event_type="AI_DOCUMENT_CLASSIFIED", entity_type="document", entity_id=document.id, action=extraction["document_type"], new_values={"document_type": extraction["document_type"], "request_id": request_id}, source="ai_document_review", status="Tamamlandı"))
                session.commit()
            except (AIUnavailableError, AIResponseError, ValueError, RuntimeError) as exc:
                session.rollback()
                session.add(AuditLog(event_type="AI_EXTRACTION_FAILED", entity_type="document", entity_id=document.id if document else None, action="manual_fallback", new_values={"error_type": type(exc).__name__}, source="ai_document_review", status="Başarısız")); session.commit()
                st.warning(f"AI hizmetine ulaşılamıyor: {exc} Belge korunmuştur; manuel girişle devam edebilirsiniz."); st.session_state.ai_manual_mode = True
        review = st.session_state.get("ai_review")
        if not review:
            if st.session_state.get("ai_manual_mode"):
                st.subheader("Manuel Belge Alanları")
                st.text_input("Fatura numarası", key="ai_manual_invoice"); st.number_input("Genel toplam", min_value=0.0, key="ai_manual_total")
                if st.button("Manuel Kaydı Onay Kuyruğuna Gönder"):
                    ApprovalWorkflowService.create(session, "AI kullanılamadı - manuel belge", "Mutabakata gönder", after={"invoice_number": st.session_state.ai_manual_invoice, "grand_total": st.session_state.ai_manual_total}); st.success("Manuel kayıt onay kuyruğuna gönderildi.")
            return
        confidence = review["confidence"]
        action_columns = st.columns(2)
        if action_columns[0].button("Yeniden Analiz Et"):
            session.add(AuditLog(event_type="AI_REANALYSIS_REQUESTED", entity_type="document", entity_id=review["document_id"], source="ai_document_review", status="Talep Edildi")); session.commit(); st.session_state.pop("ai_review", None); st.rerun()
        if action_columns[1].button("Manuel Girişe Geç"):
            st.session_state.ai_manual_mode = True; st.session_state.pop("ai_review", None); st.rerun()
        st.subheader("Belge Güven Puanı")
        st.metric(confidence["class"], f"{confidence['score']}/100")
        for reason in confidence["reasons"] + review["warnings"]: st.info(reason)
        rows = _field_rows(review["extraction"], review["validation"])
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.subheader("Alanları Kontrol Edin")
        corrected = {}
        for row in rows:
            corrected[row["Alan"]] = st.text_input(row["Alan"], value="" if row["AI Değeri"] is None else str(row["AI Değeri"]), key=f"ai_correct_{row['Alan']}") or None
        actor = st.text_input("Kontrol eden muhasebeci")
        action = st.radio("Sonraki adım", ["Mutabakata Gönder", "Onay Kuyruğuna Gönder", "Belgeyi Reddet"], horizontal=True)
        confirmed = st.checkbox("Orijinal AI değerlerini, düzeltmeleri ve doğrulama sonuçlarını kontrol ettim.")
        if st.button("İncelemeyi Kaydet", disabled=not confirmed, type="primary"):
            request = session.query(AIRequest).filter(AIRequest.request_id == review["request_id"]).first()
            extraction_row = AIExtraction(document_id=review["document_id"], ai_request_id=request.id if request else None, document_type=review["extraction"]["document_type"], original_values=review["extraction"], approved_values=corrected, validation_results=review["validation"], overall_confidence=confidence["score"], status="Reddedildi" if action == "Belgeyi Reddet" else "Onay Bekliyor")
            session.add(extraction_row); session.flush()
            original_values = ExtractionValidationService.values(review["extraction"])
            for name, metadata in review["extraction"]["fields"].items():
                field = AIExtractionField(extraction_id=extraction_row.id, field_name=name, value=metadata.get("value"), confidence=Decimal(str(metadata.get("confidence") or 0)) * 100, source_page=metadata.get("source_page"), source_text=metadata.get("source_text"), bounding_box=metadata.get("bounding_box"), status=next(row["Durum"] for row in rows if row["Alan"] == name)); session.add(field); session.flush()
                if str(original_values.get(name) or "") != str(corrected.get(name) or ""):
                    session.add(AIFieldCorrection(extraction_field_id=field.id, original_value=original_values.get(name), corrected_value=corrected.get(name), actor_name=actor))
                    session.add(AuditLog(event_type="AI_FIELD_CORRECTED", entity_type="ai_extraction_field", entity_id=field.id, old_values={"value": original_values.get(name)}, new_values={"value": corrected.get(name)}, actor_name=actor, source="ai_document_review", status="Tamamlandı"))
            session.add(DocumentConfidenceScore(document_id=review["document_id"], extraction_id=extraction_row.id, confidence_score=confidence["score"], score_class=confidence["class"], components=confidence["components"], reasons=confidence["reasons"]))
            if action != "Belgeyi Reddet": ApprovalWorkflowService.create(session, "AI-extracted document", action, source_entity_type="ai_extraction", source_entity_id=extraction_row.id, after=corrected, differences=review["validation"]["checks"], actor=actor, commit=False)
            session.add(AuditLog(event_type="AI_EXTRACTION_COMPLETED", entity_type="ai_extraction", entity_id=extraction_row.id, new_values={"confidence": confidence["score"], "accepted_fields": list(corrected)}, actor_name=actor, source="ai_document_review", status=extraction_row.status)); session.commit()
            st.success("İnceleme, orijinal değerler ve düzeltmeler kaydedildi.")
    finally: session.close()


def render_ai_accounting_assistant():
    page_header("AI Muhasebe Asistanı", "Finans, rezervasyon, tahsilat ve tedarikçi kayıtlarınız hakkında doğal dille soru sorun.")
    session = Session()
    try:
        _usage_cards(session)
        start, end = st.date_input("Dönem", value=(datetime.now().date().replace(day=1), datetime.now().date()), key="assistant_period")
        question = st.text_area("Sorunuz", placeholder="Bu ay gelir ve gider durumu nedir?")
        history = st.checkbox("Bu konuşmayı maskelenmiş özet olarak kaydet")
        if st.button("Yanıtla", disabled=not question.strip(), type="primary"):
            client = None
            try: client = OpenRouterClient(session=session) if AIModelConfigService.config()["api_key"] else None
            except Exception: client = None
            result = AccountingAssistantService.answer(session, question, datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.max.time()), client, history)
            session.add(AuditLog(event_type="AI_ASSISTANT_QUERY", entity_type="assistant_query", action=result["intent"], new_values={"analytics_function": result.get("intent"), "record_count": result["records"]}, source="ai_assistant", status="Tamamlandı")); session.commit(); st.session_state.assistant_result = result
        result = st.session_state.get("assistant_result")
        if result:
            st.info(result["answer"])
            if result.get("facts"): st.json(result["facts"])
            st.caption(f"Dönem: {result.get('period', '—')} · Aktif filtre: dönem · Veri zamanı: {result.get('timestamp', '—')} · İncelenen kayıt: {result['records']}")
            if result.get("page") and st.button(f"Destekleyici kayıtları aç: {result['page']}"): _navigate(result["page"])
    finally: session.close()


def render_ai_insights():
    page_header("AI İçgörüler", "Doğrulanmış finansal ölçümler üzerinde önceliklendirilmiş yönetim yorumları.")
    session = Session()
    try:
        _usage_cards(session); now = datetime.utcnow(); start = now - timedelta(days=30)
        facts = AccountingAssistantService.INTENTS["monthly_income_expense"][1](session, start, now)
        reconciliations = AccountingAssistantService.INTENTS["reconciliation_differences"][1](session, start, now)
        quality = AccountingAssistantService.INTENTS["document_confidence"][1](session, start, now)
        combined = {**{f"finance_{k}": v for k, v in facts.items()}, **{f"reconciliation_{k}": v for k, v in reconciliations.items()}, **{f"quality_{k}": v for k, v in quality.items()}, "record_count": facts["record_count"] + reconciliations["record_count"] + quality["record_count"]}
        detail = st.selectbox("Yorum biçimi", ["Kısa", "Detaylı", "Yönetici Özeti"])
        if st.button("Yönetim Yorumunu Oluştur / Yenile"):
            try:
                result, request_id = ManagementInsightService.generate(OpenRouterClient(session=session), combined, detail)
                request = session.query(AIRequest).filter(AIRequest.request_id == request_id).first() if request_id else None
                session.add(ManagementCommentary(ai_request_id=request.id if request else None, commentary_type="monthly", period_start=start, period_end=now, facts=combined, commentary=result["commentary"], detail_level=detail))
                session.add(AuditLog(event_type="AI_MANAGEMENT_COMMENTARY_CREATED", entity_type="management_commentary", new_values={"facts": combined, "detail": detail}, source="ai_insights", status="Tamamlandı")); session.commit(); st.session_state.management_commentary = result["commentary"]
            except AIUnavailableError as exc: st.warning(str(exc))
        st.subheader("Bugünün Özeti")
        commentary = st.session_state.get("management_commentary", "AI yorumu oluşturulmadı. Aşağıdaki ölçümler deterministik olarak hesaplandı.")
        st.info(commentary)
        columns = st.columns(4)
        columns[0].metric("Gelir", facts["income"]); columns[1].metric("Gider", facts["expense"]); columns[2].metric("Mutabakat Farkı", reconciliations["difference_amount"]); columns[3].metric("Belge Güveni", quality["average_score"] or "Veri yok")
        critical = []
        if reconciliations["critical_count"]: critical.append(("Kritik mutabakatlar", reconciliations["critical_count"], "Belge Mutabakatı"))
        if quality["low_count"]: critical.append(("Düşük güvenli belgeler", quality["low_count"], "Belge Arşivi"))
        st.subheader("Kritik Anomaliler")
        for title, value, page in critical[:5]:
            with st.container(border=True):
                st.write(f"**{title}: {value}**")
                if st.button("Kayıtları Aç", key=f"insight_{page}_{title}"): _navigate(page)
        if not critical: st.success("Öncelikli kritik içgörü bulunmadı.")
        report_rows = [{"Başlık": "Gelir", "Değer": facts["income"]}, {"Başlık": "Gider", "Değer": facts["expense"]}, {"Başlık": "Mutabakat farkı", "Değer": reconciliations["difference_amount"]}, {"Başlık": "Yorum", "Değer": commentary}]
        st.download_button("İçgörüleri PDF Olarak İndir", ReconciliationExportService.pdf(report_rows, "AI İçgörüler"), "ai-icgoruler.pdf", "application/pdf")
    finally: session.close()


def render_supplier_objection():
    page_header("Tedarikçi İtiraz Taslağı", "Yalnız doğrulanmış mutabakat farklarından düzenlenebilir bir taslak oluşturun.")
    session = Session()
    try:
        records = session.query(DocumentReconciliation).filter(DocumentReconciliation.difference_amount != 0).order_by(DocumentReconciliation.created_at.desc()).all()
        if not records: st.info("İtiraz taslağına temel olacak doğrulanmış mutabakat farkı bulunamadı."); return
        record = st.selectbox("Mutabakat", records, format_func=lambda item: f"#{item.id} · {item.status} · fark {item.difference_amount}")
        extracted = json.loads(record.extracted_json or "{}")
        incoming = extracted.get("incoming", extracted)
        facts = {"supplier": incoming.get("supplier_name"), "invoice_number": incoming.get("invoice_number"), "voucher_number": incoming.get("voucher_number"), "booking_number": incoming.get("booking_number"), "service_date": incoming.get("service_date"), "disputed_fields": json.loads(record.differences_json or "[]"), "expected_amount": str(record.expected_total or 0), "invoiced_amount": str(record.document_total or 0), "difference": str(record.difference_amount or 0), "document_references": [f"Mutabakat #{record.id}"]}
        tone = st.selectbox("Ton", ["Nazik", "Resmî", "Net", "Acil"]); language = st.selectbox("Dil", ["TR", "EN"])
        if st.button("Tedarikçiye İtiraz Taslağı Oluştur"):
            try:
                result, request_id, verified = SupplierObjectionService.generate(OpenRouterClient(session=session), facts, tone, language)
                request = session.query(AIRequest).filter(AIRequest.request_id == request_id).first()
                draft = SupplierObjectionDraft(reconciliation_id=record.id, ai_request_id=request.id if request else None, language=language, tone=tone, verified_facts=verified, subject=result["subject"], body=result["body"]); session.add(draft)
                session.add(AuditLog(event_type="AI_OBJECTION_DRAFT_CREATED", entity_type="supplier_objection_draft", new_values={"reconciliation_id": record.id, "language": language, "tone": tone}, source="supplier_objection", status="Taslak")); session.commit(); st.session_state.objection_draft = {"subject": result["subject"], "body": result["body"], "id": draft.id}
            except (AIUnavailableError, ValueError) as exc: st.warning(str(exc))
        draft = st.session_state.get("objection_draft")
        if draft:
            subject = st.text_input("Konu", value=draft["subject"]); body = st.text_area("Taslak", value=draft["body"], height=350)
            st.download_button("Metin Olarak İndir", f"{subject}\n\n{body}".encode("utf-8"), "tedarikci-itiraz.txt", "text/plain")
            st.download_button("PDF Olarak İndir", ReconciliationExportService.pdf([{"Konu": subject}, {"Metin": body}], "Tedarikçi İtirazı"), "tedarikci-itiraz.pdf", "application/pdf")
            st.caption("Taslak otomatik gönderilmez. Kopyalamadan veya e-posta taslağına aktarmadan önce kontrol edin.")
    finally: session.close()
