import json
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker

from database.db import engine
from database.models import (
    ApprovalRequest, AuditLog, Document, EmailAttachment, EmailMessage, EmailProcessingEvent, JobRun,
    Notification, NotificationEvent, ReservationCandidate, Booking,
    ReservationCandidateEvent, Supplier, WhatsAppMessage,
)
from backend.services.communication_services import (
    ApprovalQueueService, CommunicationAuditService, ReservationCandidateService,
)
from services.accounting_automation_service import ApprovalWorkflowService, ReconciliationExportService
from services.storage_service import load_document_bytes
from utils.ui import empty_state, page_header

Session = sessionmaker(bind=engine)

def _navigate(page): st.session_state.active_page = page; st.rerun()

def render_email_documents():
    page_header("E-posta Belgeleri", "Gmail üzerinden alınan ekleri inceleyin; hiçbir kayıt insan onayı olmadan faturaya dönüşmez.")
    session = Session()
    try:
        status = st.selectbox("Durum", ["Tümü", "Yeni", "Ek Bulunamadı", "Belge Algılandı", "Analiz Edildi", "Onay Bekliyor", "İşlendi", "Mükerrer", "Hatalı", "Yoksayıldı"])
        query = session.query(EmailMessage)
        if status != "Tümü": query = query.filter(EmailMessage.status == status)
        messages = query.order_by(EmailMessage.received_at.desc()).limit(500).all()
        if not messages: empty_state("E-posta belgesi yok", "Backend worker yeni Gmail iletilerini burada gösterecek."); return
        for message in messages:
            attachments = session.query(EmailAttachment).filter_by(message_id=message.id).all()
            with st.expander(f"#{message.id} · {message.subject or 'Konusuz'} · {message.status}"):
                st.caption(f"Gönderen: {message.sender or '—'} · Alınma: {message.received_at or '—'} · Ek: {len(attachments)}")
                for attachment in attachments:
                    st.write(f"{attachment.filename} · {attachment.mime_type} · {attachment.status}")
                    if attachment.document_id and st.button("Önizle", key=f"email_preview_{attachment.id}"):
                        document = session.get(Document, attachment.document_id); content = load_document_bytes(document)
                        if document.file_type == "application/pdf" and hasattr(st, "pdf"): st.pdf(content)
                        elif document.file_type.startswith("image/"): st.image(content)
                cols = st.columns(5)
                if cols[0].button("Analiz Et", key=f"email_analyze_{message.id}"): st.session_state.ai_pending_document = None; _navigate("AI Belge İnceleme")
                if cols[1].button("Mutabakata Gönder", key=f"email_reconcile_{message.id}"): _navigate("Belge Mutabakatı")
                if cols[2].button("Faturaya Dönüştür", key=f"email_invoice_{message.id}"):
                    request = ApprovalWorkflowService.create(session, "Email invoice", "Onay sonrası faturaya dönüştür", source_entity_type="email_message", source_entity_id=message.id, after={"document_ids": [a.document_id for a in attachments]}, commit=False)
                    request.source = "email"; message.status = "Onay Bekliyor"; session.commit(); st.success("Onay kuyruğuna gönderildi.")
                if cols[3].button("Yoksay", key=f"email_ignore_{message.id}"): message.status = "Yoksayıldı"; CommunicationAuditService.log(session, "EMAIL_ITEM_APPROVED", "email_message", message.id, {"action": "ignored"}); session.commit(); st.rerun()
                suppliers = session.query(Supplier).order_by(Supplier.name).all()
                if suppliers:
                    supplier = st.selectbox("Göndereni tedarikçiyle eşleştir", suppliers, format_func=lambda x: x.name, key=f"email_supplier_{message.id}")
                    if cols[4].button("Eşleştir", key=f"email_match_{message.id}"): session.add(EmailProcessingEvent(message_id=message.id, event_type="sender_supplier_matched", status="Tamamlandı", details={"supplier_id": supplier.id})); session.commit(); st.success("Gönderen eşleştirildi.")
    finally: session.close()

def render_whatsapp_candidates():
    page_header("WhatsApp Rezervasyon Adayları", "Resmî WhatsApp Business webhook mesajlarından oluşan adayları kontrol edin.")
    session = Session()
    try:
        status = st.selectbox("Durum", ["Tümü", "Yeni", "Bilgi Eksik", "İnceleme Gerekli", "Onay Bekliyor", "Rezervasyona Dönüştürüldü", "Reddedildi", "Mükerrer", "İptal Edildi"])
        query = session.query(ReservationCandidate)
        if status != "Tümü": query = query.filter(ReservationCandidate.status == status)
        candidates = query.order_by(ReservationCandidate.created_at.desc()).limit(500).all()
        if not candidates: empty_state("Rezervasyon adayı yok", "WhatsApp webhook mesajları aday olarak burada görünecek."); return
        for candidate in candidates:
            message = session.get(WhatsAppMessage, candidate.source_message_id)
            with st.expander(f"#{candidate.id} · {candidate.customer_name or candidate.phone or 'Bilinmeyen'} · {candidate.status}"):
                st.write(f"**Hizmet:** {candidate.requested_tour or 'Eksik'} · **Tarih:** {candidate.service_date or 'Eksik'} · **Yolcu:** {candidate.passenger_count or 'Eksik'}")
                st.write(f"**Otel / Alış:** {candidate.hotel or '—'} / {candidate.pickup_location or '—'} · **Fiyat:** {candidate.quoted_price or '—'} {candidate.currency or ''}")
                st.caption(f"Güven: %{candidate.confidence or 0} · Eksik: {', '.join(candidate.missing_fields or []) or 'Yok'} · Son mesaj: {(message.text_masked or '')[:250]}")
                with st.form(f"candidate_edit_{candidate.id}"):
                    tour = st.text_input("Talep edilen tur", value=candidate.requested_tour or ""); passengers = st.number_input("Yolcu", min_value=0, value=int(candidate.passenger_count or 0)); hotel = st.text_input("Otel", value=candidate.hotel or ""); pickup = st.text_input("Alış noktası", value=candidate.pickup_location or "")
                    if st.form_submit_button("Bilgileri Düzenle"):
                        candidate.requested_tour, candidate.passenger_count, candidate.hotel, candidate.pickup_location = tour or None, passengers or None, hotel or None, pickup or None
                        candidate.missing_fields = [x for x in ReservationCandidateService.REQUIRED if not getattr(candidate, x)]; candidate.status = "Bilgi Eksik" if candidate.missing_fields else "İnceleme Gerekli"; candidate.updated_at = datetime.utcnow(); session.add(ReservationCandidateEvent(candidate_id=candidate.id, event_type="updated", details={"missing_fields": candidate.missing_fields})); CommunicationAuditService.log(session, "WHATSAPP_CANDIDATE_UPDATED", "reservation_candidate", candidate.id); session.commit(); st.rerun()
                draft = ReservationCandidateService.reply_draft(candidate); st.text_area("Eksik bilgi mesajı taslağı", value=draft, key=f"reply_{candidate.id}"); st.caption("Taslak otomatik gönderilmez.")
                c1, c2, c3 = st.columns(3)
                if c1.button("Rezervasyona Dönüştür", key=f"candidate_convert_{candidate.id}"):
                    priority = ApprovalQueueService.priority(candidate.service_date, candidate.quoted_price, "Dikkat", len(candidate.missing_fields or []))
                    request = ApprovalWorkflowService.create(session, "WhatsApp reservation candidate", "Onay sonrası rezervasyon oluştur", source_entity_type="reservation_candidate", source_entity_id=candidate.id, after={"requested_tour": candidate.requested_tour, "service_date": str(candidate.service_date), "passenger_count": candidate.passenger_count, "currency": candidate.currency}, actor=None, commit=False); request.source="whatsapp"; request.severity="Dikkat"; request.priority_score=priority; request.ai_confidence=candidate.confidence; request.deterministic_checks={"missing_fields": candidate.missing_fields}; candidate.status="Onay Bekliyor"; session.commit(); st.success("Onay kuyruğuna gönderildi; rezervasyon henüz oluşturulmadı.")
                if c2.button("Reddet", key=f"candidate_reject_{candidate.id}"): candidate.status="Reddedildi"; session.add(ReservationCandidateEvent(candidate_id=candidate.id, event_type="rejected")); session.commit(); st.rerun()
                if c3.button("Mükerrer İşaretle", key=f"candidate_duplicate_{candidate.id}"): candidate.status="Mükerrer"; session.add(ReservationCandidateEvent(candidate_id=candidate.id, event_type="duplicate")); session.commit(); st.rerun()
                bookings = session.query(Booking).order_by(Booking.created_at.desc()).limit(250).all()
                if bookings and candidate.status not in {"Rezervasyona Dönüştürüldü", "Reddedildi", "Mükerrer", "İptal Edildi"}:
                    linked_booking = st.selectbox("Mevcut rezervasyon", bookings, format_func=lambda item: f"{item.booking_number} · {item.service_start_date or 'Tarih yok'}", key=f"candidate_booking_{candidate.id}")
                    if st.button("Mevcut Rezervasyona Bağla", key=f"candidate_link_{candidate.id}"):
                        candidate.booking_id = linked_booking.id; candidate.status = "Rezervasyona Dönüştürüldü"
                        session.add(ReservationCandidateEvent(candidate_id=candidate.id, event_type="linked", details={"booking_id": linked_booking.id})); CommunicationAuditService.log(session, "WHATSAPP_CANDIDATE_CONVERTED", "reservation_candidate", candidate.id, {"booking_id": linked_booking.id, "mode": "linked"}); session.commit(); st.success("Aday mevcut rezervasyona bağlandı.")
    finally: session.close()

def render_notification_center():
    page_header("Bildirim Merkezi", "Operasyonel ve finansal hatırlatmaları yetkili kayıtlarına bağlı olarak yönetin.")
    session = Session()
    try:
        unread = session.query(Notification).filter(Notification.is_read.is_(False), Notification.dismissed_at.is_(None)).count(); st.metric("Okunmamış Bildirim", unread)
        if st.button("Tümünü Okundu İşaretle"):
            session.query(Notification).filter(Notification.is_read.is_(False)).update({"is_read": True}); session.commit(); st.rerun()
        group = st.selectbox("Görünüm", ["Okunmamış", "Kritik", "Bugün", "Yaklaşan", "Tamamlanan", "Kapatılan"])
        query = session.query(Notification)
        now = datetime.utcnow()
        if group == "Okunmamış": query=query.filter(Notification.is_read.is_(False), Notification.dismissed_at.is_(None))
        elif group == "Kritik": query=query.filter(Notification.level == "Kritik", Notification.dismissed_at.is_(None))
        elif group == "Bugün": query=query.filter(Notification.due_date >= now.replace(hour=0,minute=0,second=0), Notification.due_date <= now.replace(hour=23,minute=59,second=59))
        elif group == "Yaklaşan": query=query.filter(Notification.due_date > now)
        elif group == "Tamamlanan": query=query.filter(Notification.status == "Gönderildi")
        else: query=query.filter(Notification.dismissed_at.isnot(None))
        items=query.order_by(Notification.level.desc(), Notification.due_date).limit(500).all()
        for item in items:
            with st.container(border=True):
                st.write(f"**{item.level} · {item.notification_type}**"); st.write(item.rendered_text); st.caption(f"Durum: {item.status} · Vade: {item.due_date or '—'}")
                c1,c2,c3,c4=st.columns(4)
                if c1.button("Okundu", key=f"notify_read_{item.id}"): item.is_read=True; session.add(NotificationEvent(notification_id=item.id,event_type="read")); session.commit(); st.rerun()
                if c2.button("İlgili Kaydı Aç", key=f"notify_open_{item.id}"): _navigate({"booking":"Rezervasyonlar","supplier_payment":"Tedarikçi Ödemeleri"}.get(item.entity_type,"Kontrol Merkezi"))
                if c3.button("1 Gün Ertele", key=f"notify_snooze_{item.id}"): item.scheduled_at=datetime.utcnow()+timedelta(days=1); item.status="Ertelendi"; session.add(NotificationEvent(notification_id=item.id,event_type="snoozed")); session.commit(); st.rerun()
                if c4.button("Kapat", key=f"notify_close_{item.id}"): item.dismissed_at=datetime.utcnow(); item.status="İptal Edildi"; session.add(NotificationEvent(notification_id=item.id,event_type="dismissed")); CommunicationAuditService.log(session,"REMINDER_DISMISSED","notification",item.id); session.commit(); st.rerun()
    finally: session.close()

def render_communication_reports():
    page_header("İletişim Raporları", "E-posta, WhatsApp, bildirim ve worker sonuçlarını dışa aktarın.")
    session=Session()
    try:
        email=session.query(EmailMessage).all(); candidates=session.query(ReservationCandidate).all(); notifications=session.query(Notification).all(); runs=session.query(JobRun).all()
        rows=[]
        rows += [{"Rapor":"E-posta Belgeleri","Kayıt":x.id,"Durum":x.status,"Tarih":x.received_at} for x in email]
        rows += [{"Rapor":"WhatsApp Adayları","Kayıt":x.id,"Durum":x.status,"Tarih":x.created_at} for x in candidates]
        rows += [{"Rapor":"Hatırlatma Teslimatı","Kayıt":x.id,"Durum":x.status,"Tarih":x.created_at} for x in notifications]
        rows += [{"Rapor":"Zamanlanmış İş Sağlığı","Kayıt":x.id,"Durum":x.status,"Tarih":x.started_at} for x in runs]
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        st.download_button("Excel İndir",ReconciliationExportService.excel(rows,"İletişim"),"iletisim-raporlari.xlsx")
        st.download_button("PDF İndir",ReconciliationExportService.pdf(rows,"İletişim Raporları"),"iletisim-raporlari.pdf","application/pdf")
    finally: session.close()
