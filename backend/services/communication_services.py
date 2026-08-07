import hashlib
import hmac
import json
import os
import re
import uuid
import unicodedata
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_

from database.models import (
    AIExtraction, AIRequest, ApprovalRequest, AuditLog, Booking, Document, DocumentReconciliation,
    EmailAccount, EmailAttachment, EmailIngestionBatch, EmailMessage,
    EmailProcessingEvent, JobLock, JobRun, Notification, NotificationDelivery,
    NotificationEvent, ReservationCandidate, ReservationCandidateEvent,
    ReservationCandidateField, ScheduledJob, SupplierPayment,
    WhatsAppAccount, WhatsAppConversation, WhatsAppMedia, WhatsAppMessage,
)
from services.accounting_automation_service import ApprovalWorkflowService
from services.ai_service import SensitiveDataMaskingService
from services.ai_service import AIModelConfigService, DocumentExtractionService, DocumentPreprocessingService, OpenRouterClient
from services.storage_service import store_document_bytes


SUPPORTED_MIME = {
    "application/pdf", "image/jpeg", "image/png",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel", "text/csv",
}
MAX_ATTACHMENT_BYTES = int(os.getenv("COMMUNICATION_MAX_ATTACHMENT_BYTES", "15000000"))


class EmailProvider(ABC):
    @abstractmethod
    def authenticate(self): raise NotImplementedError
    @abstractmethod
    def list_messages(self): raise NotImplementedError
    @abstractmethod
    def get_message(self, message_id): raise NotImplementedError
    @abstractmethod
    def list_attachments(self, message): raise NotImplementedError
    @abstractmethod
    def download_attachment(self, message_id, attachment_id): raise NotImplementedError
    @abstractmethod
    def add_label(self, message_id, label): raise NotImplementedError
    @abstractmethod
    def mark_processed(self, message_id): raise NotImplementedError


class GmailProvider(EmailProvider):
    """Gmail API adapter. OAuth credentials are supplied by deployment code."""
    def __init__(self, service): self.service = service
    def authenticate(self): return self.service is not None
    def list_messages(self): return self.service.users().messages().list(userId="me", q="-label:Processed-by-Accounting-App").execute().get("messages", [])
    def get_message(self, message_id): return self.service.users().messages().get(userId="me", id=message_id, format="full").execute()
    def list_attachments(self, message): return [part for part in message.get("payload", {}).get("parts", []) if part.get("body", {}).get("attachmentId")]
    def download_attachment(self, message_id, attachment_id):
        import base64
        data = self.service.users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id).execute()["data"]
        return base64.urlsafe_b64decode(data + "===")
    def add_label(self, message_id, label): return self.service.users().messages().modify(userId="me", id=message_id, body={"addLabelIds": [label]}).execute()
    def mark_processed(self, message_id): return self.add_label(message_id, os.getenv("GMAIL_PROCESSED_LABEL_ID", "Processed-by-Accounting-App"))


def validate_attachment(filename, mime_type, content):
    if len(content) > MAX_ATTACHMENT_BYTES: raise ValueError("Ek dosya izin verilen boyutu aşıyor.")
    if mime_type not in SUPPORTED_MIME: raise ValueError("Desteklenmeyen ek dosya türü.")
    signatures = {"application/pdf": content.startswith(b"%PDF"), "image/jpeg": content.startswith(b"\xff\xd8\xff"), "image/png": content.startswith(b"\x89PNG"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": content.startswith(b"PK")}
    if mime_type in signatures and not signatures[mime_type]: raise ValueError("Dosya içeriği bildirilen türle uyuşmuyor.")
    if not filename: raise ValueError("Dosya adı eksik.")


class CommunicationAuditService:
    @staticmethod
    def log(session, event, entity_type, entity_id=None, details=None, status="Tamamlandı"):
        session.add(AuditLog(event_type=event, entity_type=entity_type, entity_id=entity_id, action=event, new_values=details or {}, source="communication_backend", status=status))


class EmailAttachmentService:
    @staticmethod
    def store(session, message, attachment_meta, content):
        filename = attachment_meta.get("filename") or "attachment"; mime = attachment_meta.get("mimeType") or "application/octet-stream"
        validate_attachment(filename, mime, content); digest = hashlib.sha256(content).hexdigest()
        existing = session.query(Document).filter(Document.file_hash == digest).first()
        attachment = EmailAttachment(message_id=message.id, provider_attachment_id=attachment_meta.get("body", {}).get("attachmentId"), filename=filename, mime_type=mime, file_size=len(content), file_hash=digest, document_id=existing.id if existing else None, status="Mükerrer" if existing else "Belge Algılandı")
        session.add(attachment); session.flush()
        if existing:
            CommunicationAuditService.log(session, "EMAIL_ATTACHMENT_STORED", "email_attachment", attachment.id, {"hash": digest, "duplicate": True}); return attachment, True
        document, _ = store_document_bytes(content, filename, mime, session, commit=False); attachment.document_id = document.id
        CommunicationAuditService.log(session, "EMAIL_ATTACHMENT_STORED", "email_attachment", attachment.id, {"hash": digest, "document_id": document.id}); return attachment, False


class EmailDocumentAnalysisService:
    @staticmethod
    def analyze(session, attachment, content):
        if not AIModelConfigService.config().get("api_key") or attachment.mime_type not in {"application/pdf", "image/jpeg", "image/png"}: return False
        preprocessing = DocumentPreprocessingService.preprocess(content, attachment.filename)
        extraction, request_id = DocumentExtractionService.extract(OpenRouterClient(session=session), preprocessing)
        request = session.query(AIRequest).filter(AIRequest.request_id == request_id).first()
        session.add(AIExtraction(document_id=attachment.document_id, ai_request_id=request.id if request else None, document_type=extraction["document_type"], original_values=extraction, status="Onay Bekliyor"))
        attachment.status = "Analiz Edildi"; CommunicationAuditService.log(session, "EMAIL_DOCUMENT_ANALYZED", "email_attachment", attachment.id, {"document_type": extraction["document_type"], "request_id": request_id}); return True


class EmailIngestionService:
    def __init__(self, provider): self.provider = provider
    def sync(self, session, account):
        batch = EmailIngestionBatch(account_id=account.id, status="Çalışıyor"); session.add(batch); session.flush()
        CommunicationAuditService.log(session, "EMAIL_SYNC_STARTED", "email_ingestion_batch", batch.id)
        try:
            messages = self.provider.list_messages(); batch.message_count = len(messages)
            for ref in messages:
                provider_id = ref.get("id")
                if session.query(EmailMessage).filter(EmailMessage.provider_message_id == provider_id).first(): continue
                raw = self.provider.get_message(provider_id); headers = {item["name"].lower(): item["value"] for item in raw.get("payload", {}).get("headers", [])}
                message = EmailMessage(account_id=account.id, batch_id=batch.id, provider_message_id=provider_id, thread_id=raw.get("threadId"), sender=headers.get("from"), recipients=[headers.get("to")] if headers.get("to") else [], subject=headers.get("subject"), received_at=datetime.fromtimestamp(int(raw.get("internalDate", "0")) / 1000) if raw.get("internalDate") else datetime.utcnow(), status="Yeni")
                session.add(message); session.flush(); CommunicationAuditService.log(session, "EMAIL_MESSAGE_RECEIVED", "email_message", message.id, {"provider": account.provider, "has_subject": bool(message.subject)})
                attachments = self.provider.list_attachments(raw)
                if not attachments:
                    message.status = "Ek Bulunamadı"; batch.success_count += 1; session.commit(); self.provider.mark_processed(provider_id); continue
                stored = 0
                for meta in attachments:
                    try:
                        content = self.provider.download_attachment(provider_id, meta["body"]["attachmentId"]); attachment, duplicate = EmailAttachmentService.store(session, message, meta, content); stored += not duplicate
                        if not duplicate:
                            try:
                                EmailDocumentAnalysisService.analyze(session, attachment, content)
                            except Exception as exc:
                                session.add(EmailProcessingEvent(
                                    message_id=message.id,
                                    event_type="ai_analysis_deferred",
                                    status="Bekliyor",
                                    details={"error_code": type(exc).__name__},
                                ))
                                CommunicationAuditService.log(
                                    session,
                                    "EMAIL_DOCUMENT_ANALYSIS_DEFERRED",
                                    "email_attachment",
                                    attachment.id,
                                    {"error_code": type(exc).__name__},
                                    "Bekliyor",
                                )
                    except ValueError as exc:
                        session.add(EmailProcessingEvent(message_id=message.id, event_type="attachment_rejected", status="Hatalı", details={"error": str(exc)})); batch.failure_count += 1
                message.status = "Mükerrer" if stored == 0 else "Onay Bekliyor"
                if stored:
                    document_ids = [a.document_id for a in session.query(EmailAttachment).filter_by(message_id=message.id).all() if a.document_id]
                    message.related_document_ids = document_ids
                    ApprovalWorkflowService.create(session, "Email invoice", "Belgeyi analiz et ve mutabakata gönder", source_entity_type="email_message", source_entity_id=message.id, after={"document_ids": document_ids}, documents=document_ids, commit=False)
                    batch.success_count += 1
                session.flush()
                session.commit()
                self.provider.mark_processed(provider_id)
            batch.status = "Tamamlandı"; batch.completed_at = datetime.utcnow(); account.last_successful_sync = batch.completed_at; session.commit(); return batch
        except Exception as exc:
            session.rollback(); account.last_successful_sync = account.last_successful_sync; raise RuntimeError("E-posta sağlayıcısına ulaşılamadı; senkronizasyon daha sonra yeniden denenecek.") from exc


class ReservationCandidateService:
    REQUIRED = ("requested_tour", "service_date", "passenger_count")
    @staticmethod
    def extract_text(text, phone):
        masked = SensitiveDataMaskingService.mask_text(text); lower = text.casefold()
        passenger = re.search(r"(\d+)\s*(?:kişi|kisi|people|pax)", lower); adults = re.search(r"(\d+)\s*(?:yetişkin|yetiskin|adult)", lower); children = re.search(r"(\d+)\s*(?:çocuk|cocuk|child)", lower)
        date_match = re.search(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b", text)
        service_date = None
        if date_match:
            from services.drive_import_service import ValueNormalizationService
            service_date = ValueNormalizationService.date(date_match.group(1))
        tour = next((name for name in ("Pamukkale", "Efes", "Kuşadası", "Cappadocia", "Ephesus") if name.casefold() in lower), None)
        values = {"phone": phone, "requested_tour": tour, "service_date": service_date, "passenger_count": int(passenger.group(1)) if passenger else None, "adult_count": int(adults.group(1)) if adults else None, "child_count": int(children.group(1)) if children else None, "preferred_language": "TR" if any(x in lower for x in ("kişi", "rezervasyon", "çocuk")) else "EN", "special_requests": masked[:1000]}
        values["missing_fields"] = [field for field in ReservationCandidateService.REQUIRED if not values.get(field)]; values["confidence"] = Decimal(str(round((3 - len(values["missing_fields"])) / 3 * 100, 2))); return values

    @classmethod
    def create(cls, session, message):
        existing = session.query(ReservationCandidate).filter(ReservationCandidate.source_message_id == message.id).first()
        if existing: return existing, True
        conversation = session.get(WhatsAppConversation, message.conversation_id); values = cls.extract_text(message.text_masked or "", conversation.customer_phone)
        candidate = ReservationCandidate(conversation_id=conversation.id, source_message_id=message.id, customer_name=conversation.customer_name, status="Bilgi Eksik" if values["missing_fields"] else "İnceleme Gerekli", **values)
        session.add(candidate); session.flush()
        for name, value in values.items():
            if name not in {"missing_fields", "confidence"}: session.add(ReservationCandidateField(candidate_id=candidate.id, field_name=name, original_value=str(value) if value is not None else None, confidence=values["confidence"]))
        session.add(ReservationCandidateEvent(candidate_id=candidate.id, event_type="created", details={"missing_fields": values["missing_fields"]})); CommunicationAuditService.log(session, "WHATSAPP_CANDIDATE_CREATED", "reservation_candidate", candidate.id, {"missing_fields": values["missing_fields"], "confidence": str(values["confidence"])}); return candidate, False

    @staticmethod
    def reply_draft(candidate):
        labels = {"requested_tour": "talep ettiğiniz turu", "service_date": "hizmet tarihini", "passenger_count": "yolcu sayısını"}; missing = ", ".join(labels.get(x, x) for x in candidate.missing_fields or [])
        return f"Merhaba, rezervasyon adayınızı tamamlayabilmemiz için {missing} paylaşabilir misiniz?" if missing else "Merhaba, rezervasyon bilgilerinizi kontrol ediyoruz. Onay sonrasında size dönüş yapacağız."

    @staticmethod
    def convert_to_booking(session, candidate):
        if candidate.missing_fields: raise ValueError("Eksik zorunlu bilgiler tamamlanmadan rezervasyon oluşturulamaz.")
        if candidate.booking_id or candidate.status == "Rezervasyona Dönüştürüldü": raise ValueError("Aday daha önce rezervasyona dönüştürülmüş.")
        booking = Booking(booking_number=f"WA-{candidate.id}-{datetime.utcnow():%Y%m%d%H%M%S}", booking_date=datetime.utcnow(), service_start_date=candidate.service_date, passenger_count=candidate.passenger_count or 0, adult_count=candidate.adult_count or 0, child_count=candidate.child_count or 0, currency=candidate.currency or "TRY", grand_total=candidate.quoted_price or 0, remaining_amount=candidate.quoted_price or 0, booking_status="Onaylandı", notes=f"WhatsApp rezervasyon adayı #{candidate.id}")
        session.add(booking); session.flush(); candidate.booking_id = booking.id; candidate.status = "Rezervasyona Dönüştürüldü"; session.add(ReservationCandidateEvent(candidate_id=candidate.id, event_type="converted", details={"booking_id": booking.id})); CommunicationAuditService.log(session, "WHATSAPP_CANDIDATE_CONVERTED", "reservation_candidate", candidate.id, {"booking_id": booking.id}); return booking


class WhatsAppIngestionService:
    @staticmethod
    def verify_signature(body, signature):
        secret = os.getenv("WHATSAPP_APP_SECRET")
        if not secret: return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(); return hmac.compare_digest(expected, signature or "")
    @staticmethod
    def ingest(session, account, event_id, payload):
        existing = session.query(WhatsAppMessage).filter(WhatsAppMessage.provider_event_id == event_id).first()
        if existing: return existing, True
        phone = payload.get("from"); conversation = session.query(WhatsAppConversation).filter_by(account_id=account.id, customer_phone=phone).first()
        if not conversation: conversation = WhatsAppConversation(account_id=account.id, customer_phone=phone, customer_name=payload.get("profile_name")); session.add(conversation); session.flush()
        message = WhatsAppMessage(conversation_id=conversation.id, provider_event_id=event_id, provider_message_id=payload.get("id"), message_type=payload.get("type", "text"), text_masked=SensitiveDataMaskingService.mask_text(payload.get("text", "")), received_at=datetime.utcnow(), raw_metadata={key: value for key, value in payload.items() if key not in {"text", "token", "secret"}})
        session.add(message); session.flush(); conversation.last_message_at = message.received_at
        if message.message_type in {"image", "document"} and payload.get("media_id"):
            session.add(WhatsAppMedia(message_id=message.id, provider_media_id=payload["media_id"], mime_type=payload.get("mime_type"), status="İndirme Bekliyor"))
        CommunicationAuditService.log(session, "WHATSAPP_EVENT_RECEIVED", "whatsapp_message", message.id, {"message_type": message.message_type})
        if message.message_type in {"text", "image", "document"}: ReservationCandidateService.create(session, message)
        session.commit(); return message, False


class ApprovalQueueService:
    WEIGHTS = {"urgency": 30, "amount": 25, "severity": 20, "missing": 10, "risk": 10, "anomaly": 5}
    @classmethod
    def priority(cls, due_date=None, amount=0, severity="Bilgi", missing=0, payment_risk=False, anomaly=False):
        days = (due_date.date() - datetime.utcnow().date()).days if due_date else 30
        urgency = 1 if days <= 0 else .8 if days <= 3 else .5 if days <= 7 else 0
        amount_score = min(abs(float(amount or 0)) / 100000, 1); severity_score = {"Kritik": 1, "Dikkat": .7, "Hatırlatma": .4, "Bilgi": .1}.get(severity, .3)
        return round(urgency * 30 + amount_score * 25 + severity_score * 20 + min(missing / 3, 1) * 10 + int(payment_risk) * 10 + int(anomaly) * 5, 2)


class NotificationProvider(ABC):
    @abstractmethod
    def send(self, notification): raise NotImplementedError
    @abstractmethod
    def validate_destination(self, destination): raise NotImplementedError
    @abstractmethod
    def get_delivery_status(self, provider_id): raise NotImplementedError


class InAppNotificationProvider(NotificationProvider):
    def send(self, notification): return {"status": "Gönderildi", "provider_id": f"in-app-{notification.id}"}
    def validate_destination(self, destination): return True
    def get_delivery_status(self, provider_id): return "Gönderildi"


class EmailNotificationProvider(NotificationProvider):
    def __init__(self, sender): self.sender = sender
    def send(self, notification): return self.sender(notification.recipient, notification.rendered_text)
    def validate_destination(self, destination): return bool(destination and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", destination))
    def get_delivery_status(self, provider_id): return "Sağlayıcıdan Kontrol Edilmeli"


class WhatsAppDraftNotificationProvider(NotificationProvider):
    def send(self, notification): return {"status": "Taslak", "provider_id": None}
    def validate_destination(self, destination): return bool(destination)
    def get_delivery_status(self, provider_id): return "Taslak"


class NotificationService:
    @staticmethod
    def create(session, notification_type, entity_type, entity_id, text, level, due_date=None, channel="In-app", recipient=None):
        key = hashlib.sha256(f"{notification_type}|{entity_type}|{entity_id}|{channel}|{due_date.date() if due_date else ''}".encode()).hexdigest()
        existing = session.query(Notification).filter(Notification.idempotency_key == key).first()
        if existing: return existing, True
        item = Notification(notification_type=notification_type, entity_type=entity_type, entity_id=entity_id, channel=channel, recipient=recipient, rendered_text=text, level=level, scheduled_at=datetime.utcnow(), due_date=due_date, status="Gönderime Hazır", idempotency_key=key)
        session.add(item); session.flush(); session.add(NotificationEvent(notification_id=item.id, event_type="created")); CommunicationAuditService.log(session, "NOTIFICATION_CREATED", "notification", item.id, {"type": notification_type, "channel": channel})
        if notification_type in {"customer_collection", "supplier_payment"}:
            CommunicationAuditService.log(session, "REMINDER_CREATED", "notification", item.id, {"type": notification_type, "due_date": str(due_date) if due_date else None})
        return item, False
    @staticmethod
    def deliver(session, notification, provider, max_retries=3):
        try:
            if not provider.validate_destination(notification.recipient): raise ValueError("Geçersiz bildirim hedefi")
            response = provider.send(notification); notification.status = response["status"]; notification.sent_at = datetime.utcnow(); session.add(NotificationDelivery(notification_id=notification.id, provider=provider.__class__.__name__, attempt_number=notification.retry_count + 1, status=notification.status, provider_response=response)); CommunicationAuditService.log(session, "NOTIFICATION_SENT", "notification", notification.id); session.commit(); return True
        except Exception as exc:
            notification.retry_count += 1; notification.status = "Başarısız" if notification.retry_count >= max_retries else "Gönderime Hazır"
            if notification.status == "Gönderime Hazır":
                notification.scheduled_at = datetime.utcnow() + timedelta(minutes=min(2 ** notification.retry_count, 60))
            session.add(NotificationDelivery(notification_id=notification.id, provider=provider.__class__.__name__, attempt_number=notification.retry_count, status="Başarısız", error_code=type(exc).__name__)); CommunicationAuditService.log(session, "NOTIFICATION_FAILED", "notification", notification.id, {"error_code": type(exc).__name__}, "Başarısız"); session.commit(); return False


class ReminderService:
    PERIODS = tuple(int(value.strip()) for value in os.getenv("REMINDER_PERIODS", "30,15,7,3,1,0,-1,-7,-15").split(",") if value.strip())
    @classmethod
    def generate(cls, session, today=None):
        today = today or datetime.utcnow().date(); created = 0
        bookings = session.query(Booking).filter(Booking.remaining_amount > 0, Booking.final_payment_date.isnot(None)).all()
        for booking in bookings:
            normalized_status = "".join(character for character in unicodedata.normalize("NFKD", booking.booking_status or "") if not unicodedata.combining(character)).casefold()
            if "iptal" in normalized_status or "cancel" in normalized_status: continue
            days = (booking.final_payment_date.date() - today).days
            if days in cls.PERIODS:
                level = "Kritik" if days < 0 else "Hatırlatma"
                text = f"{booking.booking_number} numaralı rezervasyon için {booking.remaining_amount} {booking.currency} tutarındaki tahsilatın vadesine {days} gün kaldı." if days >= 0 else f"{booking.booking_number} rezervasyonunun {booking.remaining_amount} {booking.currency} tahsilatı {abs(days)} gün gecikti."
                _, duplicate = NotificationService.create(session, "customer_collection", "booking", booking.id, text, level, booking.final_payment_date); created += not duplicate
        payments = session.query(SupplierPayment).filter(SupplierPayment.remaining_amount > 0, SupplierPayment.due_date.isnot(None)).all()
        for payment in payments:
            if payment.payment_status in {"Reddedildi", "Tam Ödendi", "Mükerrer"}: continue
            critical = session.query(DocumentReconciliation).filter(DocumentReconciliation.matched_entity_type == "supplier_payment", DocumentReconciliation.matched_entity_id == payment.id, DocumentReconciliation.severity == "kritik", DocumentReconciliation.approval_status != "Onaylandı").first()
            if critical: continue
            days = (payment.due_date.date() - today).days
            if days in cls.PERIODS:
                text = f"Tedarikçi ödemesi #{payment.id}: {payment.remaining_amount} {payment.currency}, vadeye {days} gün." if days >= 0 else f"Tedarikçi ödemesi #{payment.id} {abs(days)} gün gecikti: {payment.remaining_amount} {payment.currency}."
                _, duplicate = NotificationService.create(session, "supplier_payment", "supplier_payment", payment.id, text, "Kritik" if days < 0 else "Hatırlatma", payment.due_date); created += not duplicate
        session.commit(); return created


class JobLockService:
    @staticmethod
    def acquire(session, name, owner, ttl_seconds=300):
        now = datetime.utcnow(); lock = session.query(JobLock).filter(JobLock.lock_name == name).first()
        if lock and lock.expires_at > now: return False
        if lock: lock.owner_id, lock.acquired_at, lock.expires_at = owner, now, now + timedelta(seconds=ttl_seconds)
        else: session.add(JobLock(lock_name=name, owner_id=owner, acquired_at=now, expires_at=now + timedelta(seconds=ttl_seconds)))
        session.commit(); return True
    @staticmethod
    def release(session, name, owner):
        lock = session.query(JobLock).filter_by(lock_name=name, owner_id=owner).first()
        if lock: session.delete(lock); session.commit()


class ScheduledJobService:
    @staticmethod
    def run(session, job_name, scheduled_time, callback):
        job = session.query(ScheduledJob).filter_by(job_name=job_name).first()
        if not job: job = ScheduledJob(job_name=job_name, schedule="external", is_active=True); session.add(job); session.commit()
        existing = session.query(JobRun).filter_by(job_id=job.id, scheduled_time=scheduled_time).first()
        if existing: return existing, True
        owner = str(uuid.uuid4())
        if not JobLockService.acquire(session, job_name, owner): return None, True
        run = JobRun(job_id=job.id, scheduled_time=scheduled_time, started_at=datetime.utcnow(), status="Çalışıyor"); session.add(run); session.commit(); CommunicationAuditService.log(session, "SCHEDULED_JOB_STARTED", "job_run", run.id); session.commit()
        try:
            result = callback(); run.processed_count = int(result or 0); run.success_count = run.processed_count; run.status = "Tamamlandı"; CommunicationAuditService.log(session, "SCHEDULED_JOB_COMPLETED", "job_run", run.id, {"processed": run.processed_count})
        except Exception as exc:
            session.rollback(); run = session.get(JobRun, run.id); run.status = "Başarısız"; run.failure_count = 1; run.error_summary = type(exc).__name__; CommunicationAuditService.log(session, "SCHEDULED_JOB_FAILED", "job_run", run.id, {"error_code": type(exc).__name__}, "Başarısız")
        finally:
            run.finished_at = datetime.utcnow(); session.commit(); JobLockService.release(session, job_name, owner)
        return run, False
