from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import (
    AccountReconciliationLine, Base, Booking, Collection, CurrencySettlement,
    Customer, ImportBatch, Supplier, SupplierContract, SupplierContractPrice,
    SupplierPayment, Tour, TourBudget, TourBudgetLine,
)
from services.business_value_service import (
    CurrencyManagementService, CurrentAccountReconciliationService,
    DailyWorkCenterService, SupplierContractService, TourBudgetAnalysisService,
)


@pytest.fixture
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'business.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close(); engine.dispose()


def test_contract_selects_price_valid_on_service_date(session):
    supplier = Supplier(name="Restaurant", supplier_type="Restoran"); session.add(supplier); session.flush()
    old = SupplierContract(supplier_id=supplier.id, contract_number="OLD", supplier_type="Restoran", valid_from=datetime(2025, 1, 1), valid_to=datetime(2025, 12, 31), currency="EUR")
    current = SupplierContract(supplier_id=supplier.id, contract_number="NEW", supplier_type="Restoran", valid_from=datetime(2026, 1, 1), valid_to=datetime(2026, 12, 31), currency="EUR")
    session.add_all([old, current]); session.flush()
    session.add_all([
        SupplierContractPrice(contract_id=old.id, service_code="DINNER", service_name="Dinner", expense_category="Restoran", pricing_unit="Kişi", unit_price=20, tax_rate=10),
        SupplierContractPrice(contract_id=current.id, service_code="DINNER", service_name="Dinner", expense_category="Restoran", pricing_unit="Kişi", unit_price=25, tax_rate=10),
    ]); session.commit()
    result = SupplierContractService.price_for(session, supplier.id, datetime(2026, 8, 7), "DINNER", 4)
    assert result["contract"].contract_number == "NEW"
    assert result["subtotal"] == Decimal("100.00") and result["total"] == Decimal("110.00")


def test_contract_minimum_quantity_and_no_contract(session):
    supplier = Supplier(name="Transfer"); session.add(supplier); session.flush()
    contract = SupplierContract(supplier_id=supplier.id, contract_number="T", supplier_type="Transfer", valid_from=datetime(2026, 1, 1), valid_to=datetime(2026, 12, 31), currency="TRY"); session.add(contract); session.flush()
    session.add(SupplierContractPrice(contract_id=contract.id, service_code="BUS", service_name="Bus", expense_category="Transfer", pricing_unit="Araç", unit_price=1000, tax_rate=0, minimum_quantity=2)); session.commit()
    assert SupplierContractService.price_for(session, supplier.id, datetime(2026, 5, 1), "BUS", 1)["total"] == Decimal("2000.00")
    assert SupplierContractService.price_for(session, supplier.id, datetime(2027, 5, 1), "BUS", 1) is None


def test_tour_budget_planned_actual_variance_and_break_even(session):
    tour = Tour(code="T", name="Tour"); supplier = Supplier(name="Hotel", supplier_type="Otel"); session.add_all([tour, supplier]); session.flush()
    budget = TourBudget(tour_id=tour.id, name="Budget", passenger_target=10, currency="TRY"); session.add(budget); session.flush()
    session.add_all([
        TourBudgetLine(budget_id=budget.id, line_type="Gelir", category="Satış", quantity=10, unit_amount=200, is_variable=True),
        TourBudgetLine(budget_id=budget.id, line_type="Gider", category="Otel", quantity=10, unit_amount=50, is_variable=True),
        TourBudgetLine(budget_id=budget.id, line_type="Gider", category="Transfer", quantity=1, unit_amount=500, is_variable=False),
        Booking(booking_number="B", tour_id=tour.id, grand_total=2400, exchange_rate=1, booking_status="Onaylandı"),
        SupplierPayment(supplier_id=supplier.id, tour_id=tour.id, total_debt=1200, exchange_rate=1, payment_status="Ödeme Bekliyor"),
    ]); session.commit()
    result = TourBudgetAnalysisService.calculate(session, budget)
    assert result["planned_revenue"] == Decimal("2000.00")
    assert result["planned_cost"] == Decimal("1000.00")
    assert result["actual_profit"] == Decimal("1200.00")
    assert result["profit_variance"] == Decimal("200.00")
    assert result["break_even_passengers"] == 4


def test_current_account_formula_and_customer_automation(session):
    assert CurrentAccountReconciliationService.calculate(100, 1000, 400, 50) == Decimal("650.00")
    customer = Customer(first_name="Ada", last_name="Yılmaz"); session.add(customer); session.flush()
    booking = Booking(booking_number="C1", customer_id=customer.id, booking_date=datetime(2026, 8, 1), grand_total=1000, currency="EUR", booking_status="Onaylandı"); session.add(booking); session.flush()
    session.add_all([
        Collection(booking_id=booking.id, customer_id=customer.id, collection_date=datetime(2026, 8, 2), amount=400, currency="EUR"),
        Collection(booking_id=booking.id, customer_id=customer.id, collection_date=datetime(2026, 8, 3), amount=-50, currency="EUR"),
    ]); session.commit()
    run = CurrentAccountReconciliationService.run(session, "Müşteri", customer.id, datetime(2026, 8, 1), datetime(2026, 8, 31), "EUR", 100)
    assert run.invoice_total == Decimal("1000.00") and run.payment_total == Decimal("400.00")
    assert run.credit_total == Decimal("50.00") and run.closing_balance == Decimal("650.00")
    assert session.query(AccountReconciliationLine).filter_by(run_id=run.id).count() == 3


def test_currency_realized_gain_loss_and_duplicate_protection(session):
    assert CurrencyManagementService.realized_difference(100, 30, 32, "Tahsilat") == Decimal("200.00")
    assert CurrencyManagementService.realized_difference(100, 30, 32, "Ödeme") == Decimal("-200.00")
    row = CurrencyManagementService.settle(session, "booking", 1, "Tahsilat", "EUR", 100, 30, 32, datetime(2026, 8, 7))
    assert row.recognition_try == Decimal("3000.00") and row.settlement_try == Decimal("3200.00")
    with pytest.raises(Exception):
        CurrencyManagementService.settle(session, "booking", 1, "Tahsilat", "EUR", 100, 30, 33, datetime(2026, 8, 8))
        session.flush()
    session.rollback(); assert session.query(CurrencySettlement).count() == 1


def test_daily_work_center_uses_actionable_database_records(session):
    today = datetime(2026, 8, 7)
    supplier = Supplier(name="S"); session.add(supplier); session.flush()
    session.add_all([
        Booking(booking_number="DUE", final_payment_date=today, remaining_amount=100, booking_status="Onaylandı"),
        Booking(booking_number="OVER", final_payment_date=today - timedelta(days=1), remaining_amount=50, booking_status="Onaylandı"),
        Booking(booking_number="CANCEL", final_payment_date=today, remaining_amount=100, booking_status="İptal edildi"),
        SupplierPayment(supplier_id=supplier.id, due_date=today, remaining_amount=80, payment_status="Ödeme Bekliyor"),
        ImportBatch(filename="bad.xlsx", file_hash="x", dataset_type="transaction", status="Hatalı", error_rows=1),
    ]); session.commit()
    groups = DailyWorkCenterService.items(session, today.date())
    assert [row.booking_number for row in groups["collections_due"]] == ["DUE"]
    assert len(groups["payments_due"]) == 1 and len(groups["overdue"]) == 1 and len(groups["failed_imports"]) == 1
