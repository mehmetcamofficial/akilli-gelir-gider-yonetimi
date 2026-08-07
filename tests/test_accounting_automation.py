from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import ApprovalRequest, AuditLog, BankTransaction, Base, Supplier, SupplierPayment
from services.accounting_automation_service import (
    ApprovalWorkflowService, AuditLogService, BankReconciliationService,
    BankStatementService, FieldComparisonService,
    FinancialValidationService,
)


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase2.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close(); engine.dispose()


def restaurant(**changes):
    document = {"passenger_count": 12, "invoiced_unit_price": Decimal("100"), "tax_amount": Decimal("200"), "invoice_total": Decimal("1200")}
    agency = {"passenger_count": 12, "free_guide_count": 1, "free_driver_count": 1, "other_free_person_count": 0, "agreed_unit_price": Decimal("100")}
    document.update(changes)
    return FinancialValidationService.restaurant(document, agency)


def test_restaurant_free_allowance_exact_total():
    result = restaurant()
    assert result["paying_person_count"] == 10
    assert result["expected_total"] == Decimal("1200")
    assert result["status"] == "Eşleşti"


@pytest.mark.parametrize("changes,field", [
    ({"passenger_count": 13}, "passenger_count"),
    ({"invoiced_unit_price": Decimal("110")}, "unit_price"),
    ({"unauthorized_extras": Decimal("50")}, "unauthorized_extras"),
])
def test_restaurant_detects_mismatch(changes, field):
    assert field in {item["field"] for item in restaurant(**changes)["differences"]}


def test_restaurant_duplicate_voucher():
    assert "voucher_number" in {item["field"] for item in restaurant(duplicate_voucher=True, voucher_number="V-1")["differences"]}


def test_hotel_wrong_nights_rooms_rate_and_child_fields():
    booking = {"checkin_date": datetime(2026, 1, 1), "checkout_date": datetime(2026, 1, 4), "nights": 3, "room_count": 2, "room_type": "Double", "adult_count": 2, "child_count": 1, "agreed_room_rate": Decimal("100")}
    document = {"nights": 4, "room_count": 3, "room_type": "Double", "adult_count": 2, "child_count": 2, "invoiced_room_rate": Decimal("120"), "invoice_total": Decimal("1440")}
    result = FinancialValidationService.hotel(document, booking)
    fields = {item["field"] for item in result["differences"]}
    assert {"nights", "room_count", "child_count", "room_rate"} <= fields


def test_hotel_duplicate_invoice():
    result = FinancialValidationService.hotel({"invoice_number": "H-1", "duplicate_invoice": True, "invoice_total": 0}, {"nights": 0, "room_count": 0, "agreed_room_rate": 0})
    assert "invoice_number" in {item["field"] for item in result["differences"]}


def test_supplier_partial_overpayment_and_currency():
    invoice = {"grand_total": Decimal("1000"), "currency": "EUR"}
    partial = FinancialValidationService.supplier_payment(invoice, {"amount": 300, "currency": "EUR"}, 100)
    over = FinancialValidationService.supplier_payment(invoice, {"amount": 1000, "currency": "USD"}, 100)
    assert partial["status"] == "Kısmen Ödendi"
    assert over["status"] == "Fazla Ödeme Riski"
    assert "Yanlış para birimi" in over["issues"]


def test_unreadable_field_status():
    differences = FieldComparisonService.compare({"invoice_number": None}, {"invoice_number": "INV-1"})
    assert differences[0]["status"] == "Okunamadı"


def test_approval_applies_target_and_audits_before_after(session):
    supplier = Supplier(name="Test Otel"); session.add(supplier); session.flush()
    debt = SupplierPayment(supplier_id=supplier.id, total_debt=1000, paid_amount=100, remaining_amount=900, currency="TRY")
    session.add(debt); session.commit()
    request = ApprovalWorkflowService.create(session, "Tedarikçi ödemesi", "Bakiyeyi güncelle", source_entity_type="supplier_payment", source_entity_id=debt.id, before={"paid": "100"}, after={"amount": "300"})

    def apply(db, approval):
        target = db.get(SupplierPayment, approval.source_entity_id)
        target.paid_amount += Decimal(approval.after_values["amount"])
        target.remaining_amount -= Decimal(approval.after_values["amount"])

    ApprovalWorkflowService.decide(session, request, "Onaylandı", "Ayşe", "Kontrol edildi", apply)
    session.refresh(debt)
    assert debt.paid_amount == Decimal("400.00")
    assert debt.remaining_amount == Decimal("600.00")
    log = session.query(AuditLog).filter(AuditLog.event_type == "approval_decided").one()
    assert log.old_values["status"] == "Onay Bekliyor"
    assert log.new_values["status"] == "Onaylandı"


def test_rejection_creates_no_target_change(session):
    request = ApprovalWorkflowService.create(session, "Excel import", "Kayıt oluştur", after={"amount": "10"})
    called = []
    ApprovalWorkflowService.decide(session, request, "Reddedildi", "Mehmet", apply_callback=lambda *_: called.append(True))
    assert called == []
    assert request.status == "Reddedildi"


def test_approval_callback_failure_rolls_back(session):
    request = ApprovalWorkflowService.create(session, "Manual correction", "Update", after={"value": 2})
    with pytest.raises(RuntimeError):
        ApprovalWorkflowService.decide(session, request, "Onaylandı", "Ayşe", apply_callback=lambda *_: (_ for _ in ()).throw(RuntimeError("write failed")))
    session.expire_all()
    assert session.get(ApprovalRequest, request.id).status == "Onay Bekliyor"


def test_audit_masks_secrets(session):
    AuditLogService.log(session, "test", new_values={"api_key": "secret", "amount": Decimal("4.2")}, commit=True)
    log = session.query(AuditLog).one()
    assert log.new_values == {"api_key": "***", "amount": "4.2"}


def test_bank_import_duplicate_and_split_allocation(session):
    rows = [{"Tarih": "01.08.2026", "Açıklama": "BK-1", "Alacak": "1.000,00", "Para": "TRY"}]
    mapping = {"Tarih": "transaction_date", "Açıklama": "description", "Alacak": "credit_amount", "Para": "currency"}
    first, result = BankStatementService.import_rows(session, "ekstre.csv", b"same", rows, mapping)
    second, duplicate = BankStatementService.import_rows(session, "ekstre.csv", b"same", rows, mapping)
    transaction = session.query(BankTransaction).one()
    assert result["imported"] == 1 and duplicate["duplicates"] == 1
    summary = BankReconciliationService.apply(session, transaction, [
        {"entity_type": "invoice", "entity_id": 1, "amount": "600", "score": "90"},
        {"entity_type": "invoice", "entity_id": 2, "amount": "400", "score": "80"},
    ])
    session.commit()
    assert summary["unallocated_amount"] == Decimal("0")
    assert transaction.status == "Eşleştirildi"


def test_bank_partial_and_overallocation(session):
    transaction = BankTransaction(amount=500, currency="TRY", transaction_hash="unique", status="Yeni")
    session.add(transaction); session.commit()
    partial = BankReconciliationService.validate_allocations(transaction, [{"entity_type": "invoice", "entity_id": 1, "amount": "300"}])
    assert partial["partial"] is True
    with pytest.raises(ValueError):
        BankReconciliationService.validate_allocations(transaction, [{"entity_type": "invoice", "entity_id": 1, "amount": "600"}])
