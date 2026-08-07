from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import (
    AccountReconciliationDifference, AccountReconciliationResponse, Base, BankTransaction,
    Booking, Collection, CurrentAccount, CurrentAccountMovement, Customer,
    ExchangeDifferenceEntry, OpenItem, OpenItemMatch, Supplier, SupplierPayment,
)
from services.current_account_service import (
    AccountAnalyticsService, AutomaticAccountReconciliationService,
    CurrentAccountProjectionService, DailyCurrentAccountService,
    ExchangeDifferenceService, OpenItemMatchingService,
)


@pytest.fixture
def session(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'current.db'}");Base.metadata.create_all(engine);db=sessionmaker(bind=engine)();yield db;db.close();engine.dispose()


def test_customer_invoice_collection_partial_multiple_and_idempotency(session):
    customer=Customer(first_name="Ada",last_name="Y");session.add(customer);session.flush();booking=Booking(booking_number="INV-1",customer_id=customer.id,booking_date=datetime(2026,8,1),final_payment_date=datetime(2026,8,10),grand_total=1000,currency="EUR",exchange_rate=30,booking_status="Onaylandı");session.add(booking);session.flush();session.add_all([Collection(booking_id=booking.id,customer_id=customer.id,collection_date=datetime(2026,8,5),amount=300,currency="EUR",exchange_rate=31),Collection(booking_id=booking.id,customer_id=customer.id,collection_date=datetime(2026,8,7),amount=200,currency="EUR",exchange_rate=32)]);session.commit()
    assert CurrentAccountProjectionService.rebuild(session)==3;assert CurrentAccountProjectionService.rebuild(session)==0
    assert OpenItemMatchingService.rebuild_open_items(session)==2;item=session.query(OpenItem).one();assert item.matched_amount==Decimal("500.00") and item.remaining_amount==Decimal("500.00") and item.status=="Kısmen Kapandı"


def test_supplier_invoice_payment_and_overpayment(session):
    supplier=Supplier(name="Hotel",supplier_type="Otel");session.add(supplier);session.flush();session.add(SupplierPayment(supplier_id=supplier.id,invoice_reference="H-1",service_date=datetime(2026,7,1),due_date=datetime(2026,7,15),payment_date=datetime(2026,7,10),total_debt=500,paid_amount=600,remaining_amount=-100,currency="USD",exchange_rate=35,payment_status="Ödendi"));session.commit();CurrentAccountProjectionService.rebuild(session);OpenItemMatchingService.rebuild_open_items(session);item=session.query(OpenItem).one();assert item.status=="Tam Kapandı" and item.remaining_amount==0
    payment=session.query(CurrentAccountMovement).filter_by(source_type="supplier_payment").one();OpenItemMatchingService.manual_match(session,item,[payment],[100]);assert item.status=="Fazla Ödeme" and item.remaining_amount==Decimal("-100.00")


def test_split_payment_one_payment_to_multiple_invoices(session):
    account=CurrentAccount(account_type="Müşteri Carisi",name="Split",base_currency="TRY");session.add(account);session.flush()
    for i in (1,2):
        movement=CurrentAccountMovement(account_id=account.id,transaction_date=datetime(2026,8,i),transaction_type="Fatura",document_number=f"I{i}",debit=300,credit=0,currency="TRY",exchange_rate=1,base_amount=300,source_type="invoice",source_id=i,source_hash=f"i{i}");session.add(movement);session.flush();session.add(OpenItem(account_id=account.id,movement_id=movement.id,invoice_number=f"I{i}",original_amount=300,remaining_amount=300,currency="TRY",status="Açık"))
    payment=CurrentAccountMovement(account_id=account.id,transaction_date=datetime(2026,8,3),transaction_type="Tahsilat",debit=0,credit=500,currency="TRY",exchange_rate=1,base_amount=-500,source_type="payment",source_id=1,source_hash="p");session.add(payment);session.commit();items=session.query(OpenItem).all();OpenItemMatchingService.manual_match(session,items[0],[payment],[300]);OpenItemMatchingService.manual_match(session,items[1],[payment],[200]);assert items[0].status=="Tam Kapandı" and items[1].remaining_amount==100


def test_unmatched_bank_duplicate_invoice_and_difference_detection(session):
    customer=Customer(first_name="Bank");session.add(customer);session.flush();session.add_all([Booking(booking_number="DUP",customer_id=customer.id,booking_date=datetime(2026,8,1),grand_total=100,currency="TRY",booking_status="Onaylandı"),Booking(booking_number="DUP",customer_id=customer.id,booking_date=datetime(2026,8,2),grand_total=100,currency="TRY",booking_status="Onaylandı"),BankTransaction(transaction_date=datetime(2026,8,3),counterparty="Bank",amount=50,credit_amount=50,currency="TRY",status="Yeni",transaction_hash="bank")]);session.commit();CurrentAccountProjectionService.rebuild(session);OpenItemMatchingService.rebuild_open_items(session);account=session.query(CurrentAccount).one();rec=AutomaticAccountReconciliationService.create(session,account,datetime(2026,8,1),datetime(2026,8,31),"TRY");types={x.difference_type for x in session.query(AccountReconciliationDifference).filter_by(reconciliation_id=rec.id)};assert "duplicate invoice" in types and "bank movement not linked" in types


def test_overdue_aging_and_risk(session):
    account=CurrentAccount(account_type="Müşteri Carisi",name="Risk",base_currency="TRY");session.add(account);session.flush();movement=CurrentAccountMovement(account_id=account.id,transaction_date=datetime(2026,1,1),transaction_type="Fatura",debit=10000,credit=0,currency="TRY",exchange_rate=1,base_amount=10000,source_type="invoice",source_id=1,source_hash="risk");session.add(movement);session.flush();session.add(OpenItem(account_id=account.id,movement_id=movement.id,original_amount=10000,remaining_amount=10000,currency="TRY",due_date=datetime(2026,4,1),status="Açık"));session.commit();aging=AccountAnalyticsService.aging(session,account.id,datetime(2026,8,7).date());assert aging["90+ gün"]==Decimal("10000.00");score,level,components,_=AccountAnalyticsService.risk(session,account,datetime(2026,8,7).date());assert level=="Yüksek" and score>=60 and components["maximum_overdue_days"]>90


def test_reconciliation_opening_closing_dispute_lock_and_exports(session):
    account=CurrentAccount(account_type="Tedarikçi Carisi",name="Supplier",base_currency="TRY");session.add(account);session.flush();session.add_all([CurrentAccountMovement(account_id=account.id,transaction_date=datetime(2026,7,1),transaction_type="Devir",debit=100,credit=0,currency="TRY",exchange_rate=1,base_amount=100,source_type="opening",source_id=1,source_hash="o"),CurrentAccountMovement(account_id=account.id,transaction_date=datetime(2026,8,2),transaction_type="Fatura",debit=500,credit=0,currency="TRY",exchange_rate=1,base_amount=500,source_type="invoice",source_id=2,source_hash="i"),CurrentAccountMovement(account_id=account.id,transaction_date=datetime(2026,8,5),transaction_type="Ödeme",debit=0,credit=200,currency="TRY",exchange_rate=1,base_amount=-200,source_type="payment",source_id=3,source_hash="p")]);session.commit();rec=AutomaticAccountReconciliationService.create(session,account,datetime(2026,8,1),datetime(2026,8,31),"TRY");assert rec.opening_balance==100 and rec.closing_balance==400
    with pytest.raises(ValueError):AutomaticAccountReconciliationService.record_response(session,rec,"Mutabık Değil")
    response=AutomaticAccountReconciliationService.record_response(session,rec,"Mutabık Değil",350,"Karşı kayıt farklı");assert response.difference_amount==Decimal("-50.00") and session.query(AccountReconciliationResponse).count()==1
    AutomaticAccountReconciliationService.lock(session,rec);assert rec.lock_status=="Kilitli";AutomaticAccountReconciliationService.reopen(session,rec);assert rec.lock_status=="Yeniden Açıldı";excel,pdf=AutomaticAccountReconciliationService.exports(session,rec);assert excel.startswith(b"PK") and pdf.startswith(b"%PDF")


def test_multi_currency_and_exchange_difference_requires_approval(session):
    account=CurrentAccount(account_type="Müşteri Carisi",name="FX",base_currency="TRY");session.add(account);session.flush();invoice=CurrentAccountMovement(account_id=account.id,transaction_date=datetime(2026,8,1),transaction_type="Fatura",debit=100,credit=0,currency="EUR",exchange_rate=30,base_amount=3000,source_type="invoice",source_id=1,source_hash="fxi");payment=CurrentAccountMovement(account_id=account.id,transaction_date=datetime(2026,8,2),transaction_type="Tahsilat",debit=0,credit=100,currency="EUR",exchange_rate=32,base_amount=-3200,source_type="payment",source_id=2,source_hash="fxp");session.add_all([invoice,payment]);session.commit();entry,duplicate=ExchangeDifferenceService.calculate(session,invoice,payment,Decimal("100"));assert not duplicate and entry.difference_amount==Decimal("200.00") and entry.classification=="Kazanç" and entry.approval_status=="Onay Bekliyor";same,duplicate=ExchangeDifferenceService.calculate(session,invoice,payment,Decimal("100"));assert duplicate and session.query(ExchangeDifferenceEntry).count()==1


def test_daily_refresh_is_idempotent(session):
    customer=Customer(first_name="Daily");session.add(customer);session.flush();session.add(Booking(booking_number="DAILY",customer_id=customer.id,booking_date=datetime(2026,8,1),grand_total=100,currency="TRY",booking_status="Onaylandı"));session.commit();first=DailyCurrentAccountService.refresh(session,datetime(2026,8,7).date());second=DailyCurrentAccountService.refresh(session,datetime(2026,8,7).date());assert first["movements_created"]==1 and second["movements_created"]==0 and second["risks_created"]==0
