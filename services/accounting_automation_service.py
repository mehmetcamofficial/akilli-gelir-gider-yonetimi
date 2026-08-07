"""Shared deterministic accounting automation services.

AI is limited to extraction/suggestions. Every calculation, validation and state
transition in this module is deterministic and requires explicit approval.
"""
import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

import pandas as pd
from sqlalchemy import or_

from database.models import (
    ApprovalRequest, AuditLog, BankImportBatch, BankReconciliationMatch,
    BankTransaction, Booking, Collection, Document, ImportBatchRow,
    ImportMappingTemplate, Supplier, SupplierPayment, Transaction, Voucher,
)
from services.document_reconciliation_service import OpenRouterDocumentExtractor


SECRET_KEYS = {"password", "api_key", "secret", "private_key", "database_url"}


def money(value, default=Decimal("0")):
    try:
        if isinstance(value, str):
            cleaned = value.strip().replace("₺", "").replace("€", "").replace("$", "").replace("£", "").replace(" ", "")
            if "," in cleaned and "." in cleaned:
                cleaned = cleaned.replace(".", "").replace(",", ".") if cleaned.rfind(",") > cleaned.rfind(".") else cleaned.replace(",", "")
            elif "," in cleaned:
                cleaned = cleaned.replace(",", ".")
            value = cleaned
        return Decimal(str(value)) if value not in (None, "") else default
    except (InvalidOperation, ValueError, TypeError):
        return default


def _safe(value):
    if isinstance(value, dict):
        return {key: ("***" if key.casefold() in SECRET_KEYS else _safe(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(item) for item in value]
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, datetime): return value.isoformat()
    return value


class AuditLogService:
    @staticmethod
    def log(session, event_type, *, entity_type=None, entity_id=None, batch_id=None,
            reconciliation_id=None, action=None, old_values=None, new_values=None,
            reason=None, actor_name=None, source=None, status=None, commit=False):
        entry = AuditLog(
            event_type=event_type, entity_type=entity_type, entity_id=entity_id,
            batch_id=batch_id, reconciliation_id=reconciliation_id,
            action=action or event_type, old_values=_safe(old_values),
            new_values=_safe(new_values), reason=reason, actor_name=actor_name,
            source=source, status=status,
            details_json=json.dumps(_safe(new_values or {}), ensure_ascii=False, default=str),
        )
        session.add(entry)
        if commit: session.commit()
        return entry


class DocumentExtractionService:
    """AI adapter. Failure is intentionally surfaced so manual entry can continue."""
    def __init__(self, api_key=None, transport=None):
        self.extractor = OpenRouterDocumentExtractor(api_key=api_key, transport=transport)

    def extract(self, content, filename, mime_type):
        return self.extractor.extract(content, filename, mime_type)


class DuplicateDetectionService:
    @staticmethod
    def document(session, content):
        digest = hashlib.sha256(content).hexdigest()
        return digest, session.query(Document).filter(Document.file_hash == digest).first()

    @staticmethod
    def bank_transaction(session, values):
        digest = hashlib.sha256("|".join(str(values.get(key) or "") for key in (
            "bank_account_id", "transaction_date", "reference_number", "amount", "currency", "description"
        )).encode("utf-8")).hexdigest()
        return digest, session.query(BankTransaction).filter(BankTransaction.transaction_hash == digest).first()


class FieldComparisonService:
    TEXT_FIELDS = {"supplier_name", "invoice_number", "voucher_number", "booking_number", "currency", "room_type", "board_type", "meal_type"}

    @classmethod
    def compare(cls, incoming, expected, amount_tolerance=Decimal("1"), count_tolerance=0):
        differences = []
        # Compare only fields represented by the incoming document. Agency-only
        # calculation inputs (free allowances, agreed rates) are handled by the
        # deterministic financial validators below.
        for field in sorted(set(incoming) & set(expected)):
            left, right = incoming.get(field), expected.get(field)
            if left in (None, "") or right in (None, ""):
                if left in (None, "") and right not in (None, ""):
                    differences.append({"field": field, "incoming": left, "expected": right, "status": "Okunamadı", "severity": "orta"})
                continue
            if field.endswith("count") or field in {"nights", "room_count"}:
                mismatch = abs(int(left) - int(right)) > int(count_tolerance)
            elif field.endswith("total") or field.endswith("amount") or "price" in field or field in {"tax", "extras", "discount"}:
                mismatch = abs(money(left) - money(right)) > money(amount_tolerance)
            else:
                mismatch = str(left).strip().casefold() != str(right).strip().casefold()
            if mismatch:
                differences.append({"field": field, "incoming": _safe(left), "expected": _safe(right), "status": "Kritik Uyumsuzluk", "severity": "yüksek"})
        return differences


class FinancialValidationService:
    @staticmethod
    def restaurant(document, agency, tolerance=Decimal("1")):
        total_service = int(document.get("total_service_count") or document.get("passenger_count") or 0)
        free_guide = int(agency.get("free_guide_count") or 0)
        free_driver = int(agency.get("free_driver_count") or 0)
        other_free = int(agency.get("other_free_person_count") or 0)
        paying = max(0, total_service - free_guide - free_driver - other_free)
        agreed = money(agency.get("agreed_unit_price"))
        extras = money(document.get("approved_additional_items"))
        tax = money(document.get("tax_amount"))
        discount = money(document.get("discount"))
        expected_food = money(paying) * agreed
        expected_total = expected_food + extras + tax - discount
        invoice_total = money(document.get("invoice_total") or document.get("grand_total"))
        checks = FieldComparisonService.compare(document, agency, tolerance)
        if money(document.get("invoiced_unit_price")) > agreed + money(tolerance): checks.append({"field": "unit_price", "status": "Kritik Uyumsuzluk", "severity": "yüksek", "incoming": str(document.get("invoiced_unit_price")), "expected": str(agreed)})
        if money(document.get("unauthorized_extras")) > 0: checks.append({"field": "unauthorized_extras", "status": "Kritik Uyumsuzluk", "severity": "yüksek", "incoming": str(document.get("unauthorized_extras")), "expected": "0"})
        if document.get("duplicate_voucher"): checks.append({"field": "voucher_number", "status": "Kritik Uyumsuzluk", "severity": "kritik", "incoming": document.get("voucher_number"), "expected": "Tekil voucher"})
        if document.get("duplicate_invoice"): checks.append({"field": "invoice_number", "status": "Kritik Uyumsuzluk", "severity": "kritik", "incoming": document.get("invoice_number"), "expected": "Tekil fatura"})
        if abs(invoice_total - expected_total) > money(tolerance): checks.append({"field": "invoice_total", "status": "Kritik Uyumsuzluk", "severity": "yüksek", "incoming": str(invoice_total), "expected": str(expected_total)})
        return {"paying_person_count": paying, "expected_food_total": expected_food, "expected_total": expected_total, "invoice_total": invoice_total, "difference": invoice_total - expected_total, "potential_overpayment": max(Decimal("0"), invoice_total - expected_total), "differences": checks, "status": "Eşleşti" if not checks else "Kontrol Gerekli"}

    @staticmethod
    def hotel(document, booking, tolerance=Decimal("1")):
        checkin, checkout = booking.get("checkin_date"), booking.get("checkout_date")
        nights = int(booking.get("nights") or ((checkout - checkin).days if checkin and checkout else 0))
        rooms = int(booking.get("room_count") or 0)
        rate = money(booking.get("agreed_room_rate") or booking.get("price_per_room"))
        expected_accommodation = money(nights) * money(rooms) * rate
        expected_total = expected_accommodation + money(document.get("approved_extras")) + money(document.get("tax_amount")) + money(document.get("city_tax")) + money(document.get("cancellation_penalty")) - money(document.get("discount"))
        invoice_total = money(document.get("invoice_total") or document.get("grand_total"))
        checks = FieldComparisonService.compare(document, booking, tolerance)
        if money(document.get("invoiced_room_rate")) > rate + money(tolerance): checks.append({"field": "room_rate", "status": "Kritik Uyumsuzluk", "severity": "yüksek", "incoming": str(document.get("invoiced_room_rate")), "expected": str(rate)})
        if money(document.get("unapproved_extras")) > 0: checks.append({"field": "unapproved_extras", "status": "Kritik Uyumsuzluk", "severity": "yüksek", "incoming": str(document.get("unapproved_extras")), "expected": "0"})
        if document.get("duplicate_invoice"): checks.append({"field": "invoice_number", "status": "Kritik Uyumsuzluk", "severity": "kritik", "incoming": document.get("invoice_number"), "expected": "Tekil fatura"})
        if abs(invoice_total - expected_total) > money(tolerance): checks.append({"field": "invoice_total", "status": "Kritik Uyumsuzluk", "severity": "yüksek", "incoming": str(invoice_total), "expected": str(expected_total)})
        return {"expected_nights": nights, "expected_accommodation": expected_accommodation, "expected_total": expected_total, "invoice_total": invoice_total, "difference": invoice_total - expected_total, "differences": checks, "status": "Eşleşti" if not checks else "Kontrol Gerekli"}

    @staticmethod
    def supplier_payment(invoice, payment, previous_payments=Decimal("0"), tolerance=Decimal("1")):
        total = money(invoice.get("grand_total") or invoice.get("total_debt"))
        outstanding = total - money(previous_payments)
        amount = money(payment.get("amount") or payment.get("paid_amount"))
        issues = []
        if payment.get("currency") and invoice.get("currency") and payment["currency"] != invoice["currency"]: issues.append("Yanlış para birimi")
        if payment.get("invoice_approved") is False: issues.append("Fatura onaylanmadan ödeme")
        if payment.get("document_present") is False: issues.append("Belgesiz ödeme")
        if amount > outstanding + money(tolerance): status = "Fazla Ödeme Riski"; issues.append("Ödeme kalan borçtan büyük")
        elif amount < outstanding - money(tolerance): status = "Kısmen Ödendi" if amount > 0 else "Ödeme Bekliyor"
        else: status = "Tam Ödendi"
        return {"status": status, "invoice_total": total, "previous_payments": money(previous_payments), "outstanding_balance": outstanding, "payment_amount": amount, "remaining_balance": outstanding - amount, "issues": issues}


class DocumentMatchingService:
    @staticmethod
    def bank_candidates(session, transaction, date_tolerance_days=3):
        amount = abs(money(transaction.amount))
        text = (transaction.description or "").casefold()
        candidates = []
        for row in session.query(Collection).all():
            score, reasons = Decimal("0"), []
            if abs(money(row.amount) - amount) <= Decimal("1"): score += 50; reasons.append("tutar")
            if row.transaction_reference and row.transaction_reference.casefold() in text: score += 45; reasons.append("referans")
            if row.collection_date and transaction.transaction_date and abs((row.collection_date.date() - transaction.transaction_date.date()).days) <= date_tolerance_days: score += 10; reasons.append("tarih")
            if score: candidates.append({"entity_type": "collection", "entity_id": row.id, "score": min(score, Decimal("100")), "amount": row.amount, "reason": ", ".join(reasons)})
        for row in session.query(SupplierPayment).all():
            score, reasons = Decimal("0"), []
            if abs(money(row.paid_amount) - amount) <= Decimal("1"): score += 50; reasons.append("tutar")
            if row.invoice_reference and row.invoice_reference.casefold() in text: score += 45; reasons.append("fatura")
            if score: candidates.append({"entity_type": "supplier_payment", "entity_id": row.id, "score": min(score, Decimal("100")), "amount": row.paid_amount, "reason": ", ".join(reasons)})
        for row in session.query(Transaction).filter(Transaction.invoice_number.isnot(None)).all():
            score, reasons = Decimal("0"), []
            if abs(money(row.grand_total) - amount) <= Decimal("1"): score += 50; reasons.append("tutar")
            if row.invoice_number and row.invoice_number.casefold() in text: score += 45; reasons.append("fatura")
            if score: candidates.append({"entity_type": "invoice", "entity_id": row.id, "score": min(score, Decimal("100")), "amount": row.grand_total, "reason": ", ".join(reasons)})
        for row in session.query(Booking).all():
            markers = [row.booking_number, row.voucher_number]
            if any(marker and marker.casefold() in text for marker in markers):
                candidates.append({"entity_type": "booking", "entity_id": row.id, "score": Decimal("90"), "amount": row.remaining_amount, "reason": "rezervasyon/voucher numarası"})
        return sorted(candidates, key=lambda item: item["score"], reverse=True)


class BankReconciliationService:
    @staticmethod
    def validate_allocations(transaction, allocations, tolerance=Decimal("1")):
        total = sum((money(item.get("amount")) for item in allocations), Decimal("0"))
        movement = abs(money(transaction.amount))
        if not allocations: raise ValueError("En az bir eşleşme seçilmelidir.")
        if total > movement + money(tolerance): raise ValueError("Dağıtılan tutar banka hareketinden büyük olamaz.")
        return {"movement_amount": movement, "allocated_amount": total, "unallocated_amount": movement - total, "partial": total < movement - money(tolerance)}

    @classmethod
    def apply(cls, session, transaction, allocations):
        summary = cls.validate_allocations(transaction, allocations)
        for item in allocations:
            session.add(BankReconciliationMatch(bank_transaction_id=transaction.id, entity_type=item["entity_type"], entity_id=int(item["entity_id"]), allocated_amount=money(item["amount"]), confidence=money(item.get("score")), match_reason=item.get("reason"), status="Eşleştirildi", approved_at=datetime.utcnow()))
        transaction.status = "Eşleştirildi" if not summary["partial"] else "Manuel Kaydedildi"
        return summary


class ApprovalWorkflowService:
    FINAL = {"Onaylandı", "Reddedildi", "İptal Edildi"}

    @staticmethod
    def create(session, request_type, proposed_action, *, source_entity_type=None, source_entity_id=None, before=None, after=None, differences=None, financial_effect=None, documents=None, actor=None, commit=True):
        request = ApprovalRequest(request_type=request_type, source_entity_type=source_entity_type, source_entity_id=source_entity_id, proposed_action=proposed_action, before_values=_safe(before), after_values=_safe(after), detected_differences=_safe(differences), financial_effect=financial_effect, related_documents=_safe(documents), status="Onay Bekliyor", approver_name=actor)
        session.add(request); session.flush()
        AuditLogService.log(session, "approval_requested", entity_type="approval_request", entity_id=request.id, new_values=after, actor_name=actor, status=request.status)
        if commit: session.commit()
        return request

    @classmethod
    def decide(cls, session, request, decision, actor_name, note=None, apply_callback=None):
        if request.status in cls.FINAL: raise ValueError("Bu talep daha önce sonuçlandırılmış.")
        allowed = {"Onaylandı", "Reddedildi", "Düzeltme İstendi", "Onay Bekliyor", "İptal Edildi"}
        if decision not in allowed: raise ValueError("Geçersiz onay kararı.")
        old = {"status": request.status, "approver_name": request.approver_name}
        try:
            if decision == "Onaylandı" and apply_callback:
                apply_callback(session, request)
            request.status = decision; request.approver_name = actor_name or None; request.approval_note = note; request.decided_at = datetime.utcnow()
            AuditLogService.log(session, "approval_decided", entity_type="approval_request", entity_id=request.id, action=decision, old_values=old, new_values={"status": decision}, reason=note, actor_name=actor_name, status=decision)
            session.commit()
        except Exception:
            session.rollback(); raise
        return request


class BankStatementService:
    @staticmethod
    def import_rows(session, filename, file_bytes, rows, mapping, bank_account_id=None):
        digest = hashlib.sha256(file_bytes).hexdigest()
        batch = BankImportBatch(bank_account_id=bank_account_id, filename=filename, file_hash=digest, mapping_configuration=mapping, total_rows=len(rows), status="Onaylandı")
        session.add(batch); session.flush(); imported = duplicates = 0
        for raw in rows:
            values = {target: raw.get(source) for source, target in mapping.items() if target}
            values["bank_account_id"] = bank_account_id
            tx_hash, existing = DuplicateDetectionService.bank_transaction(session, values)
            if existing: duplicates += 1; continue
            debit, credit = money(values.get("debit_amount")), money(values.get("credit_amount"))
            tx = BankTransaction(bank_account_id=bank_account_id, bank_import_batch_id=batch.id, transaction_date=pd.to_datetime(values.get("transaction_date"), dayfirst=True, errors="coerce").to_pydatetime() if pd.notna(pd.to_datetime(values.get("transaction_date"), dayfirst=True, errors="coerce")) else None, value_date=pd.to_datetime(values.get("value_date"), dayfirst=True, errors="coerce").to_pydatetime() if pd.notna(pd.to_datetime(values.get("value_date"), dayfirst=True, errors="coerce")) else None, description=str(values.get("description") or ""), reference_number=str(values.get("reference_number") or "") or None, counterparty=str(values.get("counterparty") or "") or None, counterparty_iban=str(values.get("counterparty_iban") or "") or None, currency=str(values.get("currency") or "TRY").upper(), debit_amount=debit, credit_amount=credit, amount=credit - debit, balance=money(values.get("balance"), None), raw_row=_safe(raw), transaction_hash=tx_hash, status="Yeni")
            session.add(tx); imported += 1
        batch.imported_rows, batch.duplicate_rows, batch.completed_at = imported, duplicates, datetime.utcnow()
        AuditLogService.log(session, "bank_statement_imported", entity_type="bank_import_batch", entity_id=batch.id, batch_id=batch.id, new_values={"imported": imported, "duplicates": duplicates})
        session.commit(); return batch, {"imported": imported, "duplicates": duplicates}


class ReconciliationExportService:
    @staticmethod
    def excel(rows, sheet_name="Mutabakat"):
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer: pd.DataFrame(rows).to_excel(writer, index=False, sheet_name=sheet_name[:31])
        return output.getvalue()

    @staticmethod
    def csv(rows):
        return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")

    @staticmethod
    def pdf(rows, title="İşlem Geçmişi"):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        output = BytesIO(); document = canvas.Canvas(output, pagesize=A4)
        width, height = A4; y = height - 42
        document.setTitle(title); document.setFont("Helvetica-Bold", 13); document.drawString(36, y, title); y -= 24
        document.setFont("Helvetica", 8)
        for row in rows:
            line = " | ".join(f"{key}: {value}" for key, value in row.items())
            for start in range(0, len(line), 115):
                if y < 42: document.showPage(); document.setFont("Helvetica", 8); y = height - 42
                document.drawString(36, y, line[start:start + 115]); y -= 11
            y -= 4
        document.save(); return output.getvalue()


class ReconciliationEngine:
    """Facade for all deterministic reconciliation modes."""
    restaurant = staticmethod(FinancialValidationService.restaurant)
    hotel = staticmethod(FinancialValidationService.hotel)
    supplier_payment = staticmethod(FinancialValidationService.supplier_payment)
