from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_, and_

from database.models import (
    AccountReconciliationLine, AccountReconciliationRun, ApprovalRequest, AuditLog,
    BankTransaction, Booking, Collection, DocumentReconciliation, ExchangeRate,
    ImportBatch, Supplier, SupplierContract, SupplierContractPrice, SupplierPayment,
    Tour, TourBudget, TourBudgetLine, Voucher, CurrencySettlement, ContractVersion,
    ContractPriceRule, RestaurantPriceRule, HotelPriceRule, TransferPriceRule,
    GuidePriceRule, ContractDocument, ContractPriceHistory, Notification, Document,
)
from services.storage_service import store_document_bytes


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
        "expiring_contracts": "Sözleşme ve Fiyatlar",
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
        expiring_contracts = session.query(SupplierContract).filter(SupplierContract.active.is_(True), SupplierContract.is_active.is_(True), or_(SupplierContract.valid_until.between(start, end + timedelta(days=60)), and_(SupplierContract.valid_until.is_(None), SupplierContract.valid_to.between(start, end + timedelta(days=60))))).all()
        return {
            "collections_due": collections, "payments_due": payments,
            "overdue": overdue_collections + overdue_payments, "approvals": approvals,
            "bank_unmatched": unmatched, "critical_reconciliation": critical,
            "missing_documents": missing, "failed_imports": failed,
            "expiring_contracts": expiring_contracts,
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


class ContractPriceService:
    CONTRACT_TYPES = ("Restoran", "Otel", "Transfer", "Rehber", "Aktivite / Müze", "Tekne", "Araç kiralama", "Yerel acenta", "Diğer tedarikçi")

    @staticmethod
    def validate_service_date(service_date):
        if not service_date:
            raise ValueError("Hizmet tarihi zorunludur.")
        return service_date if isinstance(service_date, datetime) else datetime.combine(service_date, datetime.min.time())

    @staticmethod
    def contract_status(contract, today=None):
        today = today or datetime.utcnow(); end = contract.valid_until or contract.valid_to
        if not (contract.active and contract.is_active) or contract.status == "İptal Edildi": return "İptal Edildi"
        if end < today: return "Süresi Doldu"
        if end <= today + timedelta(days=60): return "Süresi Yaklaşıyor"
        return "Aktif" if (contract.valid_from <= today) else "Taslak"

    @classmethod
    def find_valid_contract(cls, session, supplier_id, service_date):
        moment = cls.validate_service_date(service_date)
        contracts = session.query(SupplierContract).filter(SupplierContract.supplier_id == supplier_id, SupplierContract.active.is_(True), SupplierContract.is_active.is_(True), SupplierContract.valid_from <= moment, or_(SupplierContract.valid_until >= moment, and_(SupplierContract.valid_until.is_(None), SupplierContract.valid_to >= moment))).order_by(SupplierContract.valid_from.desc()).all()
        return contracts[0] if contracts else None

    @classmethod
    def find_valid_price(cls, session, supplier_id, service_type, service_date, tour_id=None, destination=None, selectors=None):
        moment = cls.validate_service_date(service_date); selectors = selectors or {}
        query = session.query(ContractPriceRule, ContractVersion, SupplierContract).join(ContractVersion, ContractVersion.id == ContractPriceRule.version_id).join(SupplierContract, SupplierContract.id == ContractVersion.contract_id).filter(
            SupplierContract.supplier_id == supplier_id, SupplierContract.active.is_(True), SupplierContract.is_active.is_(True), ContractVersion.active.is_(True), ContractPriceRule.active.is_(True),
            ContractPriceRule.service_type == service_type, ContractPriceRule.valid_from <= moment, ContractPriceRule.valid_until >= moment,
            or_(ContractPriceRule.exact_service_date.is_(None), func.date(ContractPriceRule.exact_service_date) == moment.date()),
            or_(ContractPriceRule.tour_id.is_(None), ContractPriceRule.tour_id == tour_id),
            or_(ContractPriceRule.destination.is_(None), ContractPriceRule.destination == destination),
        )
        candidates = query.all()
        def score(item):
            rule = item[0]
            return (4 if rule.tour_id == tour_id and rule.exact_service_date and rule.exact_service_date.date() == moment.date() else 3 if rule.tour_id == tour_id else 2 if rule.destination and rule.destination == destination else 1, rule.valid_from, rule.id)
        for rule, version, contract in sorted(candidates, key=score, reverse=True):
            subtype = None
            if service_type == "Restoran": subtype = session.query(RestaurantPriceRule).filter_by(price_rule_id=rule.id).first()
            elif service_type == "Otel": subtype = session.query(HotelPriceRule).filter_by(price_rule_id=rule.id).first()
            elif service_type == "Transfer": subtype = session.query(TransferPriceRule).filter_by(price_rule_id=rule.id).first()
            elif service_type == "Rehber": subtype = session.query(GuidePriceRule).filter_by(price_rule_id=rule.id).first()
            if subtype:
                mismatch = any(selectors.get(key) and getattr(subtype, key, None) and str(getattr(subtype, key)).casefold() != str(selectors[key]).casefold() for key in ("meal_type", "room_type", "board_type", "origin", "destination", "vehicle_type", "language", "service_type"))
                if mismatch: continue
            return {"rule": rule, "version": version, "contract": contract, "detail": subtype, "priority": score((rule, version, contract))[0]}
        return None

    @classmethod
    def validate_contract_overlap(cls, session, supplier_id, service_type, valid_from, valid_until, tour_id=None, destination=None, exclude_rule_id=None):
        query = session.query(ContractPriceRule).join(ContractVersion).join(SupplierContract).filter(SupplierContract.supplier_id == supplier_id, ContractPriceRule.service_type == service_type, ContractPriceRule.active.is_(True), ContractPriceRule.valid_from <= valid_until, ContractPriceRule.valid_until >= valid_from)
        query = query.filter(ContractPriceRule.tour_id == tour_id) if tour_id else query.filter(ContractPriceRule.tour_id.is_(None))
        query = query.filter(ContractPriceRule.destination == destination) if destination else query.filter(ContractPriceRule.destination.is_(None))
        if exclude_rule_id: query = query.filter(ContractPriceRule.id != exclude_rule_id)
        return query.first()

    @classmethod
    def calculate_expected_price(cls, match, **inputs):
        if not match: return {"status": "Sözleşme Bulunamadı", "expected_amount": None, "currency": None, "calculation_detail": "Geçerli fiyat kuralı yok."}
        rule, detail = match["rule"], match["detail"]; adults = Decimal(str(inputs.get("adults", 0))); children = Decimal(str(inputs.get("children", 0))); infants = Decimal(str(inputs.get("infants", 0)))
        if rule.pricing_model == "Sabit Grup": subtotal = money(rule.base_price); detail_text = "Sabit grup fiyatı"
        elif rule.service_type == "Restoran":
            paying = adults + children + infants; free_count = ZERO
            if detail and detail.free_person_ratio: free_count = Decimal(int(paying) // detail.free_person_ratio)
            subtotal = money(max(adults - free_count, ZERO) * rule.adult_price + children * rule.child_price + infants * rule.infant_price)
            if detail:
                subtotal += money((0 if detail.free_guide and inputs.get("guide_count") else detail.guide_price * Decimal(str(inputs.get("guide_count", 0)))) + (0 if detail.free_driver and inputs.get("driver_count") else detail.driver_price * Decimal(str(inputs.get("driver_count", 0)))) + detail.additional_service_price)
            detail_text = f"{adults} yetişkin + {children} çocuk + {infants} bebek; {free_count} ücretsiz kişi"
        elif rule.service_type == "Otel":
            rooms = Decimal(str(inputs.get("rooms", 0))); nights = Decimal(str(inputs.get("nights", 1))); room_type = str(inputs.get("room_type", "double")).lower(); room_price = getattr(detail, f"{room_type}_room", None) if detail else None
            unit = Decimal(room_price or rule.base_price); subtotal = money(unit * rooms * nights + (detail.city_tax if detail else 0) * rooms * nights + (detail.weekend_surcharge if detail and inputs.get("weekend") else 0) + (detail.holiday_surcharge if detail and inputs.get("holiday") else 0)); detail_text = f"{rooms} oda × {nights} gece"
        elif rule.service_type == "Transfer":
            subtotal = money((detail.round_trip_price if inputs.get("round_trip") else detail.one_way_price) + detail.waiting_hour_price * Decimal(str(inputs.get("waiting_hours", 0))) + detail.extra_kilometer_price * Decimal(str(inputs.get("extra_km", 0))) + detail.airport_fee + (detail.night_surcharge if inputs.get("night") else 0)); detail_text = "Gidiş-dönüş" if inputs.get("round_trip") else "Tek yön"
        elif rule.service_type == "Rehber":
            subtotal = money((detail.full_day_price if inputs.get("duration", "Tam Gün") == "Tam Gün" else detail.half_day_price) + detail.hourly_overtime * Decimal(str(inputs.get("overtime_hours", 0))) + detail.overnight_allowance * Decimal(str(inputs.get("overnights", 0))) + detail.meal_allowance + detail.transportation_allowance + detail.museum_fee); detail_text = str(inputs.get("duration", "Tam Gün"))
        else: subtotal = money(rule.base_price * Decimal(str(inputs.get("quantity", 1)))); detail_text = "Birim fiyat × miktar"
        tax = ZERO if rule.tax_included else money(subtotal * Decimal(rule.tax_rate or 0) / Decimal("100")); return {"status": "Sözleşmeyle Uyumlu", "expected_amount": subtotal + tax, "subtotal": subtotal, "tax": tax, "currency": rule.currency, "calculation_detail": detail_text, "match": match}

    @staticmethod
    def explain_price_source(match):
        if not match: return "Manuel fiyat kullanıldı; geçerli sözleşme bulunamadı."
        return f"{match['contract'].title or match['contract'].contract_number} / Versiyon {match['version'].version_number} / {match['rule'].service_name}"

    @staticmethod
    def price_difference(expected, invoice, amount_tolerance=Decimal("0.01"), percentage_tolerance=Decimal("0.5")):
        expected, invoice = money(expected), money(invoice); difference = money(invoice - expected); percentage = money(difference / expected * 100) if expected else ZERO
        status = "Sözleşmeyle Uyumlu" if abs(difference) <= amount_tolerance else "Küçük Fark" if abs(percentage) <= percentage_tolerance else "Fiyat Aşımı" if difference > 0 else "Küçük Fark"
        return {"status": status, "agreed_price": expected, "invoice_price": invoice, "absolute_difference": difference, "percentage_difference": percentage, "potential_overpayment": max(difference, ZERO)}


class ContractManagementService:
    @staticmethod
    def create_contract(session, supplier_id, contract_type, title, valid_from, valid_until, currency, **values):
        row = SupplierContract(supplier_id=supplier_id, contract_number=values.get("contract_number") or f"SC-{supplier_id}-{datetime.utcnow():%Y%m%d%H%M%S}", supplier_type=contract_type, contract_type=contract_type, title=title, description=values.get("description"), valid_from=valid_from, valid_to=valid_until, valid_until=valid_until, currency=currency, tax_included=values.get("tax_included", False), tax_rate=values.get("tax_rate", 0), payment_terms_days=values.get("payment_terms_days", 0), payment_method=values.get("payment_method"), cancellation_policy=values.get("cancellation_policy"), cancellation_rule=values.get("cancellation_policy"), notes=values.get("notes"), active=True, is_active=True, status="Aktif")
        session.add(row); session.flush(); version = ContractVersion(contract_id=row.id, version_number=1, valid_from=valid_from, valid_until=valid_until, title=title, terms=values, active=True); session.add(version); session.flush(); BusinessAuditService.log(session, "CONTRACT_CREATED", "supplier_contract", row.id, {"version_id": version.id}); return row, version

    @staticmethod
    def create_price_rule(session, contract, version, service_type, service_name, valid_from, valid_until, pricing_model, subtype_values=None, **values):
        conflict = ContractPriceService.validate_contract_overlap(session, contract.supplier_id, service_type, valid_from, valid_until, values.get("tour_id"), values.get("destination"))
        if conflict: raise ValueError("Bu tedarikçi ve hizmet için aynı tarihlerde geçerli başka bir fiyat bulunmaktadır.")
        rule = ContractPriceRule(version_id=version.id, service_type=service_type, service_name=service_name, tour_id=values.get("tour_id"), destination=values.get("destination"), exact_service_date=values.get("exact_service_date"), valid_from=valid_from, valid_until=valid_until, pricing_model=pricing_model, currency=values.get("currency") or contract.currency, base_price=values.get("base_price", 0), adult_price=values.get("adult_price", 0), child_price=values.get("child_price", 0), infant_price=values.get("infant_price", 0), tax_rate=values.get("tax_rate", contract.tax_rate or 0), tax_included=values.get("tax_included", contract.tax_included), configuration=values.get("configuration") or {}, active=True)
        session.add(rule); session.flush(); subtype_values = subtype_values or {}
        subtype_map = {"Restoran": RestaurantPriceRule, "Otel": HotelPriceRule, "Transfer": TransferPriceRule, "Rehber": GuidePriceRule}
        if service_type in subtype_map: session.add(subtype_map[service_type](price_rule_id=rule.id, **subtype_values))
        session.add(ContractPriceHistory(price_rule_id=rule.id, effective_date=valid_from, old_price=None, new_price=rule.base_price or rule.adult_price, change_percentage=None, currency=rule.currency)); BusinessAuditService.log(session, "PRICE_RULE_CREATED", "contract_price_rule", rule.id, {"contract_id": contract.id}); return rule

    @staticmethod
    def version_price(session, rule, new_price, effective_date):
        if effective_date <= rule.valid_from or effective_date > rule.valid_until: raise ValueError("Yeni fiyat tarihi mevcut fiyat döneminin içinde olmalıdır.")
        old_price = money(rule.base_price or rule.adult_price); rule.valid_until = effective_date - timedelta(seconds=1)
        new_rule = ContractPriceRule(version_id=rule.version_id, service_type=rule.service_type, service_name=rule.service_name, tour_id=rule.tour_id, destination=rule.destination, exact_service_date=rule.exact_service_date, valid_from=effective_date, valid_until=session.get(ContractVersion, rule.version_id).valid_until, pricing_model=rule.pricing_model, currency=rule.currency, base_price=new_price if rule.base_price else 0, adult_price=new_price if rule.adult_price else 0, child_price=rule.child_price, infant_price=rule.infant_price, tax_rate=rule.tax_rate, tax_included=rule.tax_included, configuration=rule.configuration, active=True)
        session.add(new_rule); session.flush(); pct = money((money(new_price) - old_price) / old_price * 100) if old_price else None; session.add(ContractPriceHistory(price_rule_id=new_rule.id, effective_date=effective_date, old_price=old_price, new_price=money(new_price), change_percentage=pct, currency=rule.currency)); BusinessAuditService.log(session, "PRICE_RULE_CHANGED", "contract_price_rule", new_rule.id, {"previous_rule_id": rule.id, "old_price": str(old_price), "new_price": str(new_price)}); return new_rule

    @staticmethod
    def store_document(session, contract, version, content, filename, mime_type):
        document, duplicate = store_document_bytes(content, filename, mime_type, session, commit=False); previous = session.query(ContractDocument).filter_by(contract_id=contract.id).order_by(ContractDocument.uploaded_at.desc()).first(); link = ContractDocument(contract_id=contract.id, version_id=version.id, document_id=document.id, file_hash=document.file_hash, drive_file_id=document.drive_file_id); session.add(link); session.flush()
        if previous: previous.replaced_by_id = link.id
        contract.document_id = document.id; BusinessAuditService.log(session, "CONTRACT_DOCUMENT_REPLACED" if previous else "CONTRACT_DOCUMENT_UPLOADED", "supplier_contract", contract.id, {"document_id": document.id, "duplicate": duplicate}); return link

    @staticmethod
    def create_expiry_notifications(session, today=None):
        today = today or datetime.utcnow().date(); created = 0
        contracts = session.query(SupplierContract).filter(SupplierContract.active.is_(True), SupplierContract.is_active.is_(True)).all()
        for contract in contracts:
            end = (contract.valid_until or contract.valid_to).date(); days = (end - today).days
            contract.status = ContractPriceService.contract_status(contract, datetime.combine(today, datetime.min.time()))
            if days in {60, 30, 15, 7, 0} or days < 0:
                key = f"contract-expiry-{contract.id}-{days}"; exists = session.query(Notification).filter_by(idempotency_key=key).first()
                if not exists:
                    supplier = session.get(Supplier, contract.supplier_id); text = f"{supplier.name} sözleşmesinin bitmesine {days} gün kaldı." if days >= 0 else f"{supplier.name} sözleşmesinin süresi doldu."
                    session.add(Notification(notification_type="contract_expiry", entity_type="supplier_contract", entity_id=contract.id, channel="In-app", rendered_text=text, level="Kritik" if days <= 7 else "Hatırlatma", scheduled_at=datetime.utcnow(), due_date=contract.valid_until or contract.valid_to, status="Gönderime Hazır", idempotency_key=key)); created += 1
                    if days < 0: BusinessAuditService.log(session, "CONTRACT_EXPIRED", "supplier_contract", contract.id)
        session.commit(); return created

    @staticmethod
    def benchmark(session, service_type, service_name, service_date):
        moment = ContractPriceService.validate_service_date(service_date); rules = session.query(ContractPriceRule).filter(ContractPriceRule.service_type == service_type, ContractPriceRule.service_name == service_name, ContractPriceRule.active.is_(True), ContractPriceRule.valid_from <= moment, ContractPriceRule.valid_until >= moment).all(); prices = sorted([money(rule.base_price or rule.adult_price) for rule in rules])
        if not prices: return []
        average = money(sum(prices, ZERO) / len(prices)); median = prices[len(prices)//2] if len(prices)%2 else money((prices[len(prices)//2-1]+prices[len(prices)//2])/2)
        return [{"rule_id": rule.id, "supplier": session.get(Supplier, session.get(SupplierContract, session.get(ContractVersion, rule.version_id).contract_id).supplier_id).name, "price": money(rule.base_price or rule.adult_price), "minimum": prices[0], "maximum": prices[-1], "average": average, "median": median, "deviation_from_median": money(((money(rule.base_price or rule.adult_price)-median)/median*100) if median else 0), "currency": rule.currency} for rule in rules]

    @classmethod
    def simulate(cls, session, tour_id, service_date, adults, children, rooms, vehicle_type, guide_language, expected_revenue):
        total = ZERO; lines = []
        suppliers = session.query(Supplier).all()
        for service_type in ("Restoran", "Otel", "Transfer", "Rehber", "Aktivite / Müze"):
            best = None
            for supplier in suppliers:
                selectors = {"vehicle_type": vehicle_type, "language": guide_language}
                match = ContractPriceService.find_valid_price(session, supplier.id, service_type, service_date, tour_id=tour_id, selectors=selectors)
                if match:
                    result = ContractPriceService.calculate_expected_price(match, adults=adults, children=children, rooms=rooms, nights=1, vehicle_type=vehicle_type, language=guide_language, duration="Tam Gün")
                    if best is None or result["expected_amount"] < best["expected_amount"]: best = {**result, "supplier": supplier.name, "source": ContractPriceService.explain_price_source(match)}
            if best: total += best["expected_amount"]; lines.append({"service": service_type, **best})
        passengers = adults + children; revenue = money(expected_revenue); profit = money(revenue-total); margin = money(profit/revenue*100) if revenue else ZERO; revenue_pp = revenue/Decimal(str(passengers)) if passengers else ZERO; break_even = int((total/revenue_pp).to_integral_value(rounding="ROUND_CEILING")) if revenue_pp else None
        return {"lines": lines, "total_supplier_cost": money(total), "cost_per_passenger": money(total/passengers) if passengers else ZERO, "expected_revenue": revenue, "estimated_gross_profit": profit, "expected_profit_margin": margin, "break_even_passenger_count": break_even}

    @classmethod
    def import_rows(cls, session, rows):
        imported = 0
        for data in rows:
            supplier = session.query(Supplier).filter(Supplier.name == str(data.get("supplier", "")).strip()).first()
            if not supplier: continue
            start = data["valid_from"] if isinstance(data["valid_from"], datetime) else datetime.fromisoformat(str(data["valid_from"]))
            end = data["valid_until"] if isinstance(data["valid_until"], datetime) else datetime.fromisoformat(str(data["valid_until"]))
            contract_type = str(data["contract_type"]); service = str(data["service"]); contract, version = cls.create_contract(session, supplier.id, contract_type, f"{service} İçe Aktarım", start, end, str(data.get("currency", "TRY")))
            cls.create_price_rule(session, contract, version, contract_type, service, start, end, data.get("pricing_model", "Kişi Başı"), currency=contract.currency, adult_price=data.get("adult_price", 0), child_price=data.get("child_price", 0), base_price=data.get("room_price") or data.get("vehicle_price") or data.get("guide_price") or 0, tax_rate=data.get("tax", 0)); imported += 1
        BusinessAuditService.log(session, "CONTRACT_IMPORT_COMPLETED", "supplier_contract", details={"imported": imported}); session.commit(); return imported


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
