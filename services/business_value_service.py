from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_

from database.models import (
    AccountReconciliationLine, AccountReconciliationRun, ApprovalRequest, AuditLog,
    BankTransaction, Booking, Collection, DocumentReconciliation, ExchangeRate,
    ImportBatch, Supplier, SupplierContract, SupplierContractPrice, SupplierPayment,
    Tour, TourBudget, TourBudgetLine, Voucher, CurrencySettlement,
)


ZERO = Decimal("0")


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class BusinessAuditService:
    @staticmethod
    def log(session, event, entity_type, entity_id=None, details=None):
        session.add(AuditLog(event_type=event, entity_type=entity_type, entity_id=entity_id, action=event, new_values=details or {}, source="business_value", status="Tamamlandı"))


class DailyWorkCenterService:
    CANCELLED_STATUSES = ("İptal", "İptal edildi", "İptal Edildi", "Cancelled", "Canceled")
    ROUTES = {
        "collections_due": "Tahsilatlar", "payments_due": "Tedarikçi Ödemeleri",
        "overdue": "Bildirim Merkezi", "approvals": "Onay Bekleyen İşlemler",
        "bank_unmatched": "Banka Hareketleri ve Mutabakat", "critical_reconciliation": "Belge Mutabakatı",
        "missing_documents": "Belge Arşivi", "failed_imports": "Excel Veri Aktarımı",
    }

    @classmethod
    def items(cls, session, today=None):
        today = today or datetime.utcnow().date(); start = datetime.combine(today, datetime.min.time()); end = start + timedelta(days=1)
        active_booking = or_(Booking.booking_status.is_(None), Booking.booking_status.notin_(cls.CANCELLED_STATUSES))
        collections = session.query(Booking).filter(active_booking, Booking.remaining_amount > 0, Booking.final_payment_date >= start, Booking.final_payment_date < end).all()
        payments = session.query(SupplierPayment).filter(SupplierPayment.remaining_amount > 0, SupplierPayment.due_date >= start, SupplierPayment.due_date < end, ~SupplierPayment.payment_status.in_(["Tam Ödendi", "Reddedildi", "Mükerrer"])).all()
        overdue_collections = session.query(Booking).filter(active_booking, Booking.remaining_amount > 0, Booking.final_payment_date < start).all()
        overdue_payments = session.query(SupplierPayment).filter(SupplierPayment.remaining_amount > 0, SupplierPayment.due_date < start, ~SupplierPayment.payment_status.in_(["Tam Ödendi", "Reddedildi", "Mükerrer"])).all()
        approvals = session.query(ApprovalRequest).filter(ApprovalRequest.status == "Onay Bekliyor").all()
        unmatched = session.query(BankTransaction).filter(BankTransaction.status.in_(["Yeni", "Eşleşmedi", "Onay Bekliyor"])).all()
        critical = session.query(DocumentReconciliation).filter(DocumentReconciliation.severity.ilike("kritik"), DocumentReconciliation.approval_status != "Onaylandı").all()
        upcoming = session.query(Booking).filter(active_booking, Booking.service_start_date >= start, Booking.service_start_date < end + timedelta(days=7)).all()
        booking_ids_with_voucher = {row[0] for row in session.query(Voucher.booking_id).filter(Voucher.booking_id.isnot(None)).all()}
        missing = [row for row in upcoming if row.id not in booking_ids_with_voucher]
        failed = session.query(ImportBatch).filter(or_(ImportBatch.status.in_(["Hatalı", "Başarısız"]), ImportBatch.error_rows > 0)).all()
        return {
            "collections_due": collections, "payments_due": payments,
            "overdue": overdue_collections + overdue_payments, "approvals": approvals,
            "bank_unmatched": unmatched, "critical_reconciliation": critical,
            "missing_documents": missing, "failed_imports": failed,
        }


class SupplierContractService:
    TYPES = ("Restoran", "Otel", "Transfer", "Rehber", "Diğer")

    @staticmethod
    def valid_contract(session, supplier_id, service_date, service_code=None):
        moment = service_date if isinstance(service_date, datetime) else datetime.combine(service_date, datetime.min.time())
        query = session.query(SupplierContract).filter(
            SupplierContract.supplier_id == supplier_id, SupplierContract.is_active.is_(True),
            SupplierContract.valid_from <= moment, SupplierContract.valid_to >= moment,
        ).order_by(SupplierContract.valid_from.desc(), SupplierContract.id.desc())
        if service_code:
            query = query.join(SupplierContractPrice).filter(SupplierContractPrice.service_code == service_code)
        return query.first()

    @classmethod
    def price_for(cls, session, supplier_id, service_date, service_code, quantity=1):
        contract = cls.valid_contract(session, supplier_id, service_date, service_code)
        if not contract:
            return None
        price = session.query(SupplierContractPrice).filter_by(contract_id=contract.id, service_code=service_code).first()
        if not price:
            return None
        effective_quantity = max(Decimal(str(quantity or 0)), Decimal(str(price.minimum_quantity or 0)))
        subtotal = money(effective_quantity * Decimal(price.unit_price))
        tax = money(subtotal * Decimal(price.tax_rate or 0) / Decimal("100"))
        return {"contract": contract, "price": price, "quantity": effective_quantity, "subtotal": subtotal, "tax": tax, "total": subtotal + tax}

    @classmethod
    def price_for_category(cls, session, supplier_id, service_date, category, quantity=1):
        contract = cls.valid_contract(session, supplier_id, service_date)
        if not contract:
            return None
        price = session.query(SupplierContractPrice).filter(
            SupplierContractPrice.contract_id == contract.id,
            SupplierContractPrice.expense_category == category,
        ).order_by(SupplierContractPrice.id.desc()).first()
        return cls.price_for(session, supplier_id, service_date, price.service_code, quantity) if price else None


class TourBudgetAnalysisService:
    @staticmethod
    def calculate(session, budget):
        lines = session.query(TourBudgetLine).filter_by(budget_id=budget.id).all()
        planned_revenue = sum((money(x.quantity * x.unit_amount) for x in lines if x.line_type == "Gelir"), ZERO)
        planned_cost = sum((money(x.quantity * x.unit_amount) for x in lines if x.line_type == "Gider"), ZERO)
        bookings = session.query(Booking).filter(Booking.tour_id == budget.tour_id, or_(Booking.booking_status.is_(None), Booking.booking_status.notin_(DailyWorkCenterService.CANCELLED_STATUSES))).all()
        actual_revenue = sum((money(booking.grand_total * (booking.exchange_rate or 1)) for booking in bookings), ZERO)
        payments = session.query(SupplierPayment).filter(SupplierPayment.tour_id == budget.tour_id, ~SupplierPayment.payment_status.in_(["Reddedildi", "Mükerrer"])).all()
        actual_cost = sum((money(payment.total_debt * (payment.exchange_rate or 1)) for payment in payments), ZERO)
        planned_categories = defaultdict(lambda: ZERO)
        for line in lines:
            if line.line_type == "Gider": planned_categories[line.category] += money(line.quantity * line.unit_amount)
        actual_categories = defaultdict(lambda: ZERO)
        for payment in payments:
            supplier = session.get(Supplier, payment.supplier_id)
            actual_categories[(supplier.supplier_type if supplier else None) or "Diğer"] += money(payment.total_debt * (payment.exchange_rate or 1))
        categories = sorted(set(planned_categories) | set(actual_categories))
        fixed_cost = sum((money(x.quantity * x.unit_amount) for x in lines if x.line_type == "Gider" and not x.is_variable), ZERO)
        variable_cost = sum((money(x.quantity * x.unit_amount) for x in lines if x.line_type == "Gider" and x.is_variable), ZERO)
        target = Decimal(str(budget.passenger_target or 0)); revenue_per_passenger = planned_revenue / target if target else ZERO; variable_per_passenger = variable_cost / target if target else ZERO
        contribution = revenue_per_passenger - variable_per_passenger
        break_even = int((fixed_cost / contribution).to_integral_value(rounding="ROUND_CEILING")) if contribution > 0 else None
        return {
            "planned_revenue": money(planned_revenue), "planned_cost": money(planned_cost),
            "actual_revenue": money(actual_revenue), "actual_cost": money(actual_cost),
            "planned_profit": money(planned_revenue - planned_cost), "actual_profit": money(actual_revenue - actual_cost),
            "profit_variance": money((actual_revenue - actual_cost) - (planned_revenue - planned_cost)),
            "break_even_passengers": break_even,
            "categories": [{"category": category, "planned": money(planned_categories[category]), "actual": money(actual_categories[category]), "variance": money(actual_categories[category] - planned_categories[category])} for category in categories],
        }


class CurrentAccountReconciliationService:
    @staticmethod
    def calculate(opening_balance, invoices, payments, credits):
        return money(money(opening_balance) + money(invoices) - money(payments) - money(credits))

    @classmethod
    def run(cls, session, party_type, party_id, start, end, currency, opening_balance=ZERO):
        start_dt = start if isinstance(start, datetime) else datetime.combine(start, datetime.min.time()); end_dt = end if isinstance(end, datetime) else datetime.combine(end, datetime.max.time())
        entries = []
        if party_type == "Tedarikçi":
            rows = session.query(SupplierPayment).filter(SupplierPayment.supplier_id == party_id, SupplierPayment.currency == currency, SupplierPayment.service_date >= start_dt, SupplierPayment.service_date <= end_dt).all()
            for row in rows:
                invoice = max(money(row.total_debt), ZERO); payment = max(money(row.paid_amount), ZERO); credit = abs(min(money(row.total_debt), ZERO))
                entries.extend([(row.service_date or row.due_date or start_dt, "Fatura", row.invoice_reference, invoice, ZERO, "supplier_payment", row.id), (row.payment_date or row.due_date or start_dt, "Ödeme", row.document_reference, ZERO, payment, "supplier_payment", row.id)] if payment else [(row.service_date or row.due_date or start_dt, "Fatura", row.invoice_reference, invoice, ZERO, "supplier_payment", row.id)])
                if credit: entries.append((row.service_date or start_dt, "İade/Alacak", row.invoice_reference, ZERO, credit, "supplier_payment", row.id))
        else:
            rows = session.query(Booking).filter(Booking.customer_id == party_id, Booking.currency == currency, Booking.booking_date >= start_dt, Booking.booking_date <= end_dt, or_(Booking.booking_status.is_(None), Booking.booking_status.notin_(DailyWorkCenterService.CANCELLED_STATUSES))).all()
            for row in rows:
                entries.append((row.booking_date or start_dt, "Fatura", row.booking_number, max(money(row.grand_total), ZERO), ZERO, "booking", row.id))
                for payment in session.query(Collection).filter(Collection.booking_id == row.id, Collection.currency == currency, Collection.collection_date >= start_dt, Collection.collection_date <= end_dt).all():
                    amount = money(payment.amount); entries.append((payment.collection_date, "Tahsilat" if amount >= 0 else "İade/Alacak", payment.receipt_number, ZERO, abs(amount), "collection", payment.id))
        invoice_total = sum((entry[3] for entry in entries if entry[1] == "Fatura"), ZERO); payment_total = sum((entry[4] for entry in entries if entry[1] in {"Ödeme", "Tahsilat"}), ZERO); credit_total = sum((entry[4] for entry in entries if entry[1] == "İade/Alacak"), ZERO)
        closing = cls.calculate(opening_balance, invoice_total, payment_total, credit_total)
        run = AccountReconciliationRun(party_type=party_type, party_id=party_id, period_start=start_dt, period_end=end_dt, currency=currency, opening_balance=money(opening_balance), invoice_total=money(invoice_total), payment_total=money(payment_total), credit_total=money(credit_total), closing_balance=closing)
        session.add(run); session.flush(); running = money(opening_balance)
        for entry in sorted(entries, key=lambda item: item[0]):
            running = money(running + entry[3] - entry[4]); session.add(AccountReconciliationLine(run_id=run.id, entry_date=entry[0], entry_type=entry[1], reference=entry[2], debit=entry[3], credit=entry[4], running_balance=running, source_entity_type=entry[5], source_entity_id=entry[6]))
        BusinessAuditService.log(session, "ACCOUNT_RECONCILIATION_COMPLETED", "account_reconciliation_run", run.id, {"closing_balance": str(closing), "currency": currency}); session.commit(); return run


class CurrencyManagementService:
    CURRENCIES = ("TRY", "EUR", "USD", "GBP")

    @staticmethod
    def save_rate(session, rate_date, currency, try_rate, source="Manuel"):
        if currency not in CurrencyManagementService.CURRENCIES or currency == "TRY": raise ValueError("Yalnızca EUR, USD ve GBP için kur girilebilir.")
        moment = rate_date if isinstance(rate_date, datetime) else datetime.combine(rate_date, datetime.min.time())
        row = session.query(ExchangeRate).filter(func.date(ExchangeRate.rate_date) == moment.date(), ExchangeRate.currency == currency).first()
        if row: row.try_rate, row.source = Decimal(str(try_rate)), source
        else: row = ExchangeRate(rate_date=moment, currency=currency, try_rate=Decimal(str(try_rate)), source=source); session.add(row)
        session.flush(); BusinessAuditService.log(session, "EXCHANGE_RATE_SAVED", "exchange_rate", row.id, {"currency": currency, "date": str(moment.date())}); session.commit(); return row

    @staticmethod
    def realized_difference(foreign_amount, recognition_rate, settlement_rate, direction):
        raw = money(foreign_amount) * (Decimal(str(settlement_rate)) - Decimal(str(recognition_rate)))
        return money(raw if direction == "Tahsilat" else -raw)

    @classmethod
    def settle(cls, session, entity_type, entity_id, direction, currency, foreign_amount, recognition_rate, settlement_rate, settlement_date):
        if currency not in cls.CURRENCIES: raise ValueError("Desteklenmeyen para birimi.")
        difference = cls.realized_difference(foreign_amount, recognition_rate, settlement_rate, direction)
        row = CurrencySettlement(entity_type=entity_type, entity_id=entity_id, direction=direction, currency=currency, foreign_amount=money(foreign_amount), recognition_rate=Decimal(str(recognition_rate)), settlement_rate=Decimal(str(settlement_rate)), recognition_try=money(Decimal(str(foreign_amount)) * Decimal(str(recognition_rate))), settlement_try=money(Decimal(str(foreign_amount)) * Decimal(str(settlement_rate))), exchange_difference=difference, settlement_date=settlement_date)
        session.add(row); session.flush(); BusinessAuditService.log(session, "EXCHANGE_DIFFERENCE_RECORDED", "currency_settlement", row.id, {"difference": str(difference)}); session.commit(); return row
