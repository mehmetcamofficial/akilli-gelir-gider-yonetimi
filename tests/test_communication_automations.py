from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.services.communication_services import (
    EmailIngestionService, EmailProvider, InAppNotificationProvider,
    JobLockService, NotificationProvider, NotificationService,
    ReminderService, ReservationCandidateService, ScheduledJobService,
    WhatsAppIngestionService,
)
from database.models import (
    ApprovalRequest, BankAccount, Base, Booking, EmailAccount, EmailAttachment,
    EmailMessage, JobRun, Notification, ReservationCandidate, Supplier,
    SupplierPayment, WhatsAppAccount, WhatsAppConversation, WhatsAppMedia,
)
from services.accounting_automation_service import ApprovalWorkflowService


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'communication.db'}"); Base.metadata.create_all(engine); db = sessionmaker(bind=engine)(); yield db; db.close(); engine.dispose()


class FakeEmailProvider(EmailProvider):
    def __init__(self, messages, contents=None, fail=False): self.messages, self.contents, self.fail, self.processed = messages, contents or {}, fail, []
    def authenticate(self): return True
    def list_messages(self):
        if self.fail: raise ConnectionError("secret provider failure")
        return [{"id": item["id"]} for item in self.messages]
    def get_message(self, message_id): return next(item for item in self.messages if item["id"] == message_id)
    def list_attachments(self, message): return message.get("payload", {}).get("parts", [])
    def download_attachment(self, message_id, attachment_id): return self.contents[attachment_id]
    def add_label(self, message_id, label): self.processed.append(message_id)
    def mark_processed(self, message_id): self.processed.append(message_id)


def gmail_message(message_id, parts):
    return {"id": message_id, "threadId": "t", "internalDate": "1700000000000", "payload": {"headers": [{"name": "From", "value": "supplier@example.com"}, {"name": "Subject", "value": "Invoice"}], "parts": parts}}


def attachment(identifier, mime="application/pdf", filename="invoice.pdf"):
    return {"filename": filename, "mimeType": mime, "body": {"attachmentId": identifier}}


def test_email_pdf_no_attachment_duplicate_and_approval(session, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    account = EmailAccount(provider="gmail", account_address="finance@example.com"); session.add(account); session.commit()
    provider = FakeEmailProvider([gmail_message("m1", [attachment("a1")]), gmail_message("m2", []), gmail_message("m3", [attachment("a3")])], {"a1": b"%PDF-1.4 invoice", "a3": b"%PDF-1.4 invoice"})
    EmailIngestionService(provider).sync(session, account)
    statuses = {row.provider_message_id: row.status for row in session.query(EmailMessage).all()}
    assert statuses == {"m1": "Onay Bekliyor", "m2": "Ek Bulunamadı", "m3": "Mükerrer"}
    assert session.query(ApprovalRequest).count() == 1
    assert provider.processed == ["m1", "m2", "m3"]


def test_email_unsupported_and_provider_failure(session, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path); account = EmailAccount(provider="gmail", account_address="x@y.com"); session.add(account); session.commit()
    provider = FakeEmailProvider([gmail_message("bad", [attachment("bad", "application/x-msdownload", "bad.exe")])], {"bad": b"MZ"})
    batch = EmailIngestionService(provider).sync(session, account)
    assert batch.failure_count == 1
    previous = account.last_successful_sync
    with pytest.raises(RuntimeError): EmailIngestionService(FakeEmailProvider([], fail=True)).sync(session, account)
    session.refresh(account); assert account.last_successful_sync == previous


def _whatsapp_account(session):
    account = WhatsAppAccount(phone_number_id="phone-1", display_name="Agency"); session.add(account); session.commit(); return account


def test_whatsapp_turkish_english_missing_duplicate_and_image(session):
    account = _whatsapp_account(session)
    message, duplicate = WhatsAppIngestionService.ingest(session, account, "evt-tr", {"id":"wam1","from":"90555111","type":"text","text":"15.09.2026 Pamukkale 3 kişi 2 yetişkin 1 çocuk"})
    candidate = session.query(ReservationCandidate).filter_by(source_message_id=message.id).one()
    assert candidate.passenger_count == 3 and candidate.preferred_language == "TR" and not candidate.booking_id
    _, duplicate = WhatsAppIngestionService.ingest(session, account, "evt-tr", {"id":"wam1","from":"90555111","type":"text","text":"duplicate"}); assert duplicate
    message2, _ = WhatsAppIngestionService.ingest(session, account, "evt-en", {"id":"wam2","from":"447700","type":"text","text":"Ephesus on 16/09/2026"})
    candidate2 = session.query(ReservationCandidate).filter_by(source_message_id=message2.id).one(); assert "passenger_count" in candidate2.missing_fields and candidate2.preferred_language == "EN"
    WhatsAppIngestionService.ingest(session, account, "evt-image", {"id":"wam3","from":"447700","type":"image","text":"","media_id":"media1","mime_type":"image/jpeg"})
    assert session.query(WhatsAppMedia).count() == 1


def test_candidate_requires_approval_and_duplicate_conversion_protected(session):
    account = _whatsapp_account(session); message, _ = WhatsAppIngestionService.ingest(session, account, "evt", {"id":"w","from":"9055","type":"text","text":"15.09.2026 Efes 2 kişi"}); candidate=session.query(ReservationCandidate).one()
    request = ApprovalWorkflowService.create(session, "WhatsApp reservation candidate", "Rezervasyon oluştur", source_entity_type="reservation_candidate", source_entity_id=candidate.id, after={})
    assert session.query(Booking).count() == 0
    ApprovalWorkflowService.decide(session, request, "Onaylandı", "Accountant", apply_callback=lambda db, _: ReservationCandidateService.convert_to_booking(db, candidate))
    assert session.query(Booking).count() == 1
    with pytest.raises(ValueError): ReservationCandidateService.convert_to_booking(session, candidate)


def test_rejection_creates_no_booking(session):
    request = ApprovalWorkflowService.create(session, "WhatsApp reservation candidate", "Rezervasyon", after={})
    ApprovalWorkflowService.decide(session, request, "Reddedildi", "Accountant", apply_callback=lambda *_: session.add(Booking(booking_number="BAD")))
    assert session.query(Booking).count() == 0


def test_upcoming_overdue_cancelled_and_duplicate_reminders(session):
    today = datetime(2026, 8, 7)
    session.add_all([
        Booking(booking_number="UP", final_payment_date=today + timedelta(days=7), remaining_amount=100, currency="TRY", booking_status="Onaylandı"),
        Booking(booking_number="CANCEL", final_payment_date=today, remaining_amount=100, currency="TRY", booking_status="İptal"),
    ])
    supplier=Supplier(name="S"); session.add(supplier); session.flush(); session.add(SupplierPayment(supplier_id=supplier.id,due_date=today-timedelta(days=1),remaining_amount=200,total_debt=200,currency="EUR",payment_status="Ödeme Bekliyor")); session.commit()
    assert ReminderService.generate(session, today.date()) == 2
    assert ReminderService.generate(session, today.date()) == 0
    assert session.query(Notification).count() == 2


class FailingProvider(NotificationProvider):
    def send(self, notification): raise ConnectionError("provider secret")
    def validate_destination(self, destination): return True
    def get_delivery_status(self, provider_id): return "unknown"


def test_notification_retry_and_in_app_fallback(session):
    notification, _ = NotificationService.create(session,"test","booking",1,"Text","Bilgi"); session.commit()
    assert not NotificationService.deliver(session, notification, FailingProvider(), max_retries=2); assert notification.status == "Gönderime Hazır"
    assert not NotificationService.deliver(session, notification, FailingProvider(), max_retries=2); assert notification.status == "Başarısız"
    fallback, _ = NotificationService.create(session,"test","booking",2,"Text","Bilgi")
    assert NotificationService.deliver(session, fallback, InAppNotificationProvider())


def test_job_lock_idempotency_failure_recovery(session):
    assert JobLockService.acquire(session,"job","owner")
    assert not JobLockService.acquire(session,"job","other")
    JobLockService.release(session,"job","owner"); assert JobLockService.acquire(session,"job","other"); JobLockService.release(session,"job","other")
    scheduled=datetime(2026,8,7,7)
    run, duplicate=ScheduledJobService.run(session,"daily",scheduled,lambda:3); assert not duplicate and run.status=="Tamamlandı"
    same, duplicate=ScheduledJobService.run(session,"daily",scheduled,lambda:99); assert duplicate and session.query(JobRun).count()==1
    failed, duplicate=ScheduledJobService.run(session,"daily",scheduled+timedelta(days=1),lambda:(_ for _ in ()).throw(RuntimeError("secret details"))); assert failed.status=="Başarısız" and failed.error_summary=="RuntimeError"


def test_fastapi_health_and_whatsapp_verification(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    response = client.get("/webhooks/whatsapp", params={"hub.mode":"subscribe","hub.challenge":"42","hub.verify_token":"verify-me"})
    assert response.status_code == 200 and response.json() == 42
    assert client.post("/webhooks/whatsapp", content=b"{}", headers={"x-hub-signature-256":"bad"}).status_code == 401
