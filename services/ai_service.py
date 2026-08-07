import base64
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from io import BytesIO

import streamlit as st
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError
from sqlalchemy import func, or_

from database.models import (
    AIRequest, AIUsageLog, AnomalyExplanation, AssistantQuery, BankTransaction,
    Booking, Cancellation, Collection, Document, DocumentConfidenceScore, DocumentReconciliation,
    ManagementCommentary, RestaurantReconciliation, Supplier, SupplierObjectionDraft,
    SupplierPayment, Tour, Transaction, CurrentAccount, CurrentAccountMovement,
    OpenItem, AccountReconciliation,
)


EXTRACTION_FIELDS = [
    "document_type", "supplier_name", "customer_name", "tax_number", "invoice_number",
    "voucher_number", "booking_number", "tour_name", "document_date", "service_date",
    "check_in_date", "check_out_date", "passenger_count", "adult_count", "child_count",
    "guide_count", "driver_count", "room_count", "night_count", "room_type", "board_type",
    "currency", "exchange_rate", "unit_price", "subtotal", "discount", "tax_rate",
    "tax_amount", "additional_costs", "grand_total", "paid_amount", "remaining_amount",
    "payment_method", "bank_reference", "description",
]
DOCUMENT_TYPES = ["restaurant_invoice", "hotel_invoice", "supplier_invoice", "customer_sales_invoice", "voucher", "receipt", "payment_receipt", "pos_slip", "bank_document", "transfer_document", "guide_expense_document", "passenger_list", "price_agreement", "unknown_document"]


class AIUnavailableError(RuntimeError):
    """OpenRouter could not provide a usable response."""


class AIResponseError(ValueError):
    """The AI response failed strict structural or traceability validation."""


class AIModelConfigService:
    DEFAULT_MODEL = "openai/gpt-4o-mini"

    @staticmethod
    def _secret(name, default):
        try: return st.secrets.get(name, default)
        except Exception: return default

    @classmethod
    def config(cls):
        return {
            "api_key": cls._secret("OPENROUTER_API_KEY", None),
            "model": cls._secret("OPENROUTER_MODEL", cls.DEFAULT_MODEL),
            "max_pages": int(cls._secret("AI_MAX_PAGES", 8)),
            "max_image_bytes": int(cls._secret("AI_MAX_IMAGE_BYTES", 5_000_000)),
            "max_requests_per_analysis": int(cls._secret("AI_MAX_REQUESTS_PER_ANALYSIS", 10)),
            "max_retries": int(cls._secret("AI_MAX_RETRIES", 2)),
            "daily_warning": int(cls._secret("AI_DAILY_REQUEST_WARNING", 100)),
            "monthly_cost_warning": Decimal(str(cls._secret("AI_MONTHLY_COST_WARNING", 20))),
            "extraction_timeout": int(cls._secret("AI_EXTRACTION_TIMEOUT", 90)),
            "assistant_timeout": int(cls._secret("AI_ASSISTANT_TIMEOUT", 45)),
        }


class SensitiveDataMaskingService:
    PATTERNS = [
        (re.compile(r"\b[1-9]\d{10}\b"), "[TCKN MASKELENDİ]"),
        (re.compile(r"\b[A-Z][0-9]{7,9}\b", re.I), "[PASAPORT MASKELENDİ]"),
        (re.compile(r"\bTR\d{24}\b", re.I), lambda m: m.group(0)[:4] + "********************" + m.group(0)[-4:]),
        (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[KART MASKELENDİ]"),
        (re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[E-POSTA MASKELENDİ]"),
        (re.compile(r"(?:\+90|0)?5\d{9}\b"), "[TELEFON MASKELENDİ]"),
    ]

    @classmethod
    def mask_text(cls, text):
        result = str(text or "")
        for pattern, replacement in cls.PATTERNS: result = pattern.sub(replacement, result)
        return result

    @classmethod
    def minimize_facts(cls, facts, allowed_fields):
        return {key: cls.mask_text(value) if isinstance(value, str) else value for key, value in facts.items() if key in allowed_fields}


class AIUsageAuditService:
    PRICES = {"openai/gpt-4o-mini": (Decimal("0.00000015"), Decimal("0.00000060"))}

    @classmethod
    def record(cls, session, request_id, request_type, model, usage, duration_ms, status, summary=None, error_code=None):
        input_tokens = int((usage or {}).get("prompt_tokens", 0)); output_tokens = int((usage or {}).get("completion_tokens", 0))
        rates = cls.PRICES.get(model, (Decimal("0"), Decimal("0")))
        cost = Decimal(input_tokens) * rates[0] + Decimal(output_tokens) * rates[1]
        request = AIRequest(request_id=request_id, request_type=request_type, model=model, masked_summary=summary or {}, status=status, error_code=error_code)
        session.add(request)
        session.add(AIUsageLog(request_id=request_id, request_type=request_type, model=model, input_tokens=input_tokens, output_tokens=output_tokens, estimated_cost=cost, duration_ms=duration_ms, status=status))
        session.flush(); return request


class OpenRouterClient:
    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, session=None, transport=None, config=None):
        self.session, self.transport = session, transport
        self.config = config or AIModelConfigService.config()

    def request(self, request_type, messages, schema=None, timeout=None, summary=None):
        if not self.config.get("api_key") and not self.transport: raise AIUnavailableError("AI hizmetine ulaşılamıyor. Manuel girişle devam edin.")
        request_id = str(uuid.uuid4()); started = time.monotonic()
        payload = {"model": self.config["model"], "messages": messages, "temperature": 0}
        if schema: payload["response_format"] = {"type": "json_schema", "json_schema": {"name": request_type, "strict": True, "schema": schema}}
        last_error = None
        for attempt in range(self.config["max_retries"] + 1):
            try:
                response = self.transport(payload) if self.transport else self._post(payload, timeout or self.config["extraction_timeout"])
                content = response["choices"][0]["message"]["content"]
                result = json.loads(content) if isinstance(content, str) else content
                if schema and not isinstance(result, dict): raise AIResponseError("Yapılandırılmış AI yanıtı geçersiz.")
                if self.session: AIUsageAuditService.record(self.session, request_id, request_type, self.config["model"], response.get("usage"), int((time.monotonic() - started) * 1000), "Başarılı", summary)
                return result, request_id
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, AIResponseError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.config["max_retries"]:
                    if schema and isinstance(exc, (json.JSONDecodeError, AIResponseError, KeyError, TypeError)):
                        payload["messages"] = list(payload["messages"]) + [{"role": "user", "content": "Önceki yanıt geçerli şemaya uymadı. Değer uydurmadan yalnız geçerli JSON ile yeniden yanıtla."}]
                    time.sleep(min(2 ** attempt, 4)); continue
        if self.session: AIUsageAuditService.record(self.session, request_id, request_type, self.config["model"], {}, int((time.monotonic() - started) * 1000), "Başarısız", summary, type(last_error).__name__)
        raise AIUnavailableError("AI hizmetine ulaşılamıyor veya geçerli yanıt alınamadı. Manuel girişle devam edin.") from last_error

    def _post(self, payload, timeout):
        request = urllib.request.Request(self.URL, data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {self.config['api_key']}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response: return json.loads(response.read().decode())


class DocumentPreprocessingService:
    SUPPORTED = {"pdf", "jpg", "jpeg", "png"}

    @classmethod
    def preprocess(cls, content, filename, config=None):
        config = config or AIModelConfigService.config(); suffix = filename.rsplit(".", 1)[-1].lower()
        if suffix not in cls.SUPPORTED: raise ValueError("Desteklenmeyen dosya türü.")
        return cls._cached(hashlib.sha256(content).hexdigest(), content, suffix, config["max_pages"], config["max_image_bytes"])

    @staticmethod
    @lru_cache(maxsize=64)
    def _cached(digest, content, suffix, max_pages, max_bytes):
        pages, warnings = [], []
        try:
            if suffix == "pdf":
                import fitz
                pdf = fitz.open(stream=content, filetype="pdf")
                if pdf.needs_pass: raise ValueError("Şifre korumalı PDF açılamıyor.")
                if len(pdf) > max_pages: warnings.append(f"Belge {len(pdf)} sayfa; ilk {max_pages} sayfa işlendi.")
                for number, page in enumerate(pdf[:max_pages], 1): pages.append((number, page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png")))
            else: pages = [(1, content)]
            processed = []
            for number, image_bytes in pages:
                image = Image.open(BytesIO(image_bytes)); image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((2200, 2200)); gray = ImageOps.grayscale(image)
                variance = float(__import__("numpy").array(gray).var())
                blank = variance < 12
                if variance < 120 and not blank: image = ImageEnhance.Contrast(image).enhance(1.35)
                out = BytesIO(); image.save(out, "JPEG", quality=85, optimize=True)
                data = out.getvalue()
                if len(data) > max_bytes: warnings.append(f"{number}. sayfa büyük olduğu için sıkıştırıldı.")
                processed.append({"page": number, "bytes": data[:max_bytes], "blank": blank, "quality": max(0, min(100, variance / 5))})
            return {"hash": digest, "pages": processed, "warnings": warnings, "page_count": len(pages)}
        except (UnidentifiedImageError, OSError, RuntimeError) as exc: raise ValueError("Belge bozuk veya okunamıyor.") from exc


class ExtractionValidationService:
    CURRENCIES = {"TRY", "EUR", "USD", "GBP"}
    REQUIRED = {"supplier_invoice": ["supplier_name", "invoice_number", "document_date", "currency", "grand_total"], "restaurant_invoice": ["supplier_name", "invoice_number", "voucher_number", "grand_total"], "hotel_invoice": ["supplier_name", "invoice_number", "booking_number", "grand_total"]}

    @staticmethod
    def values(extraction): return {key: (item or {}).get("value") if isinstance(item, dict) else item for key, item in extraction.get("fields", {}).items()}

    @classmethod
    def validate(cls, extraction, duplicate=False, internal_match=True):
        values = cls.values(extraction); checks = []; arithmetic_ok = True
        def issue(field, message, status="Hesaplama Hatası"): checks.append({"field": field, "status": status, "message": message})
        subtotal, tax, discount, total = (Decimal(str(values.get(k) or 0)) for k in ("subtotal", "tax_amount", "discount", "grand_total"))
        if total and abs(subtotal + tax - discount - total) > Decimal("1"): arithmetic_ok = False; issue("grand_total", "Ara toplam + vergi - indirim, genel toplamla uyuşmuyor.")
        paid, remaining = Decimal(str(values.get("paid_amount") or 0)), Decimal(str(values.get("remaining_amount") or 0))
        if paid > total: arithmetic_ok = False; issue("paid_amount", "Ödenen tutar toplamdan büyük.")
        if total and abs(total - paid - remaining) > Decimal("1"): arithmetic_ok = False; issue("remaining_amount", "Kalan tutar doğru hesaplanmamış.")
        if values.get("currency") and values["currency"] not in cls.CURRENCIES: issue("currency", "Para birimi geçersiz.", "Kontrol Edin")
        if values.get("tax_rate") is not None and not Decimal("0") <= Decimal(str(values["tax_rate"])) <= Decimal("100"): issue("tax_rate", "Vergi oranı geçersiz.")
        if values.get("invoice_number") and not re.match(r"^[\w./-]{2,100}$", str(values["invoice_number"])): issue("invoice_number", "Fatura numarası biçimi geçersiz.", "Kontrol Edin")
        if duplicate: issue("file_hash", "Aynı belge daha önce yüklenmiş.", "Kayıtla Uyuşmuyor")
        if not internal_match: issue("internal_match", "İlgili acenta kaydıyla eşleşmedi.", "Kayıtla Uyuşmuyor")
        required = cls.REQUIRED.get(extraction.get("document_type"), [])
        missing = [field for field in required if values.get(field) in (None, "")]
        for field in missing: issue(field, "Zorunlu alan okunamadı.", "Okunamadı")
        return {"checks": checks, "arithmetic_consistent": arithmetic_ok, "required": required, "missing_required": missing, "duplicate": duplicate, "internal_match": internal_match}


class DocumentConfidenceService:
    DEFAULT_WEIGHTS = {"required_fields": 20, "model_confidence": 15, "arithmetic": 20, "internal_match": 20, "image_quality": 10, "identity_fields": 10, "integrity": 5}

    @classmethod
    def calculate(cls, extraction, validation, preprocessing, weights=None):
        weights = weights or cls.DEFAULT_WEIGHTS; fields = extraction.get("fields", {}); required = validation["required"]
        completion = 1 if not required else 1 - len(validation["missing_required"]) / len(required)
        confidences = [float(item.get("confidence", 0)) for item in fields.values() if isinstance(item, dict)]
        model = sum(confidences) / len(confidences) if confidences else 0
        qualities = [page["quality"] / 100 for page in preprocessing.get("pages", []) if not page["blank"]]
        components = {"required_fields": completion, "model_confidence": model, "arithmetic": float(validation["arithmetic_consistent"]), "internal_match": float(validation["internal_match"]), "image_quality": sum(qualities) / len(qualities) if qualities else 0, "identity_fields": sum(bool(ExtractionValidationService.values(extraction).get(k)) for k in ("invoice_number", "supplier_name", "voucher_number", "booking_number")) / 4, "integrity": float(not validation["duplicate"])}
        score = round(sum(weights[key] * components[key] for key in weights), 2)
        label = "Yüksek Güven" if score >= 90 else "İyi" if score >= 75 else "Kontrol Gerekli" if score >= 50 else "Düşük Güven"
        reasons = ["Matematiksel kontroller tutarlı." if validation["arithmetic_consistent"] else "Toplam tutar hesaplaması belgeyle uyuşmuyor.", "İç kayıtla eşleşiyor." if validation["internal_match"] else "İç kayıt eşleşmesi bulunamadı."]
        if validation["missing_required"]: reasons.append("Okunamayan zorunlu alanlar: " + ", ".join(validation["missing_required"]))
        return {"score": score, "class": label, "components": components, "reasons": reasons}


class DocumentExtractionService:
    @staticmethod
    def schema():
        field_meta = {
            "type": "object", "additionalProperties": False,
            "required": ["value", "confidence", "source_page", "source_text", "bounding_box"],
            "properties": {
                "value": {},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "source_page": {"type": ["integer", "null"]},
                "source_text": {"type": ["string", "null"]},
                "bounding_box": {"type": ["array", "null"], "items": {"type": "number"}},
            },
        }
        return {"type": "object", "additionalProperties": False, "required": ["document_type", "fields", "unreadable_fields", "warnings", "document_language", "overall_confidence"], "properties": {"document_type": {"type": "string", "enum": DOCUMENT_TYPES}, "fields": {"type": "object", "additionalProperties": False, "required": EXTRACTION_FIELDS, "properties": {key: field_meta for key in EXTRACTION_FIELDS}}, "unreadable_fields": {"type": "array", "items": {"type": "string"}}, "warnings": {"type": "array", "items": {"type": "string"}}, "document_language": {"type": ["string", "null"]}, "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1}}}

    @classmethod
    def extract(cls, client, preprocessing):
        content = [{"type": "text", "text": "Belgeyi sınıflandır ve okunamayan değerleri null bırakarak şemaya göre çıkar."}]
        for page in preprocessing["pages"]:
            if not page["blank"]: content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(page["bytes"]).decode()}})
        result, request_id = client.request("document_extraction", [{"role": "user", "content": content}], cls.schema(), summary={"document_hash": preprocessing["hash"], "pages": preprocessing["page_count"]})
        cls.validate_structure(result); return result, request_id

    @staticmethod
    def validate_structure(result):
        if set(result.get("fields", {})) != set(EXTRACTION_FIELDS): raise AIResponseError("AI alan şeması eksik veya fazla alan içeriyor.")
        for name, item in result["fields"].items():
            if not isinstance(item, dict) or not {"value", "confidence", "source_page", "source_text", "bounding_box"} <= set(item): raise AIResponseError(f"{name} alan metadatası geçersiz.")
            if item["value"] is None and name not in result.get("unreadable_fields", []): result.setdefault("unreadable_fields", []).append(name)


class SafeAnalyticsService:
    @staticmethod
    def current_account_balances(session, start, end):
        accounts=session.query(CurrentAccount).all();rows=[]
        for account in accounts:
            movements=session.query(CurrentAccountMovement).filter(CurrentAccountMovement.account_id==account.id,CurrentAccountMovement.transaction_date>=start,CurrentAccountMovement.transaction_date<=end).all();balance=sum((Decimal(x.debit or 0)-Decimal(x.credit or 0) for x in movements),Decimal(0));rows.append({"account":account.name,"type":account.account_type,"balance":str(balance)})
        rows.sort(key=lambda x:abs(Decimal(x["balance"])),reverse=True);return {"accounts":rows[:20],"record_count":len(rows)}
    @staticmethod
    def current_account_over_90(session,start,end):
        cutoff=datetime.utcnow()-timedelta(days=90);items=session.query(OpenItem).filter(OpenItem.remaining_amount>0,OpenItem.due_date<cutoff).all();return {"items":[{"account":session.get(CurrentAccount,x.account_id).name,"invoice":x.invoice_number,"amount":str(x.remaining_amount),"currency":x.currency} for x in items[:100]],"amount":str(sum((Decimal(x.remaining_amount) for x in items),Decimal(0))),"record_count":len(items)}
    @staticmethod
    def disputed_accounts(session,start,end):
        rows=session.query(AccountReconciliation).filter(AccountReconciliation.status=="Mutabık Değil",AccountReconciliation.prepared_at>=start,AccountReconciliation.prepared_at<=end).all();return {"count":len(rows),"amount":str(sum((abs(Decimal(x.closing_balance)) for x in rows),Decimal(0))),"record_count":len(rows)}
    @staticmethod
    def income_expense(session, start, end):
        rows = session.query(Transaction).filter(Transaction.transaction_date >= start, Transaction.transaction_date <= end, Transaction.is_deleted.is_(False)).all()
        income = sum((Decimal(row.grand_total or 0) for row in rows if row.transaction_type == "income"), Decimal(0)); expense = sum((Decimal(row.grand_total or 0) for row in rows if row.transaction_type == "expense"), Decimal(0))
        return {"income": str(income), "expense": str(expense), "net": str(income - expense), "record_count": len(rows)}
    @staticmethod
    def overdue_receivables(session, start, end):
        rows = session.query(Booking).filter(Booking.remaining_amount > 0, Booking.final_payment_date < datetime.utcnow()).all(); return {"amount": str(sum((Decimal(r.remaining_amount or 0) for r in rows), Decimal(0))), "record_count": len(rows)}
    @staticmethod
    def overdue_payables(session, start, end):
        rows = session.query(SupplierPayment).filter(SupplierPayment.remaining_amount > 0, SupplierPayment.due_date < datetime.utcnow()).all(); return {"amount": str(sum((Decimal(r.remaining_amount or 0) for r in rows), Decimal(0))), "record_count": len(rows)}
    @staticmethod
    def bank_unmatched(session, start, end):
        rows = session.query(BankTransaction).filter(BankTransaction.status.in_(["Yeni", "Eşleşme Önerildi", "Onay Bekliyor"])).all(); return {"amount": str(sum((abs(Decimal(r.amount or 0)) for r in rows), Decimal(0))), "record_count": len(rows)}
    @staticmethod
    def reconciliation(session, start, end):
        rows = session.query(DocumentReconciliation).filter(DocumentReconciliation.created_at >= start, DocumentReconciliation.created_at <= end).all(); return {"difference_amount": str(sum((abs(Decimal(r.difference_amount or 0)) for r in rows), Decimal(0))), "record_count": len(rows), "critical_count": sum(r.severity == "kritik" for r in rows)}
    @staticmethod
    def document_quality(session, start, end):
        rows = session.query(DocumentConfidenceScore).filter(DocumentConfidenceScore.created_at >= start, DocumentConfidenceScore.created_at <= end).all(); return {"average_score": round(sum(float(r.confidence_score) for r in rows) / len(rows), 2) if rows else None, "low_count": sum(float(r.confidence_score) < 50 for r in rows), "record_count": len(rows)}
    @staticmethod
    def collections(session, start, end):
        rows = session.query(Collection).filter(Collection.collection_date >= start, Collection.collection_date <= end).all(); return {"amount": str(sum((Decimal(r.amount or 0) for r in rows), Decimal(0))), "record_count": len(rows)}
    @staticmethod
    def supplier_spending(session, start, end):
        rows = session.query(SupplierPayment).filter(SupplierPayment.service_date >= start, SupplierPayment.service_date <= end).all(); return {"amount": str(sum((Decimal(r.total_debt or 0) for r in rows), Decimal(0))), "supplier_count": len({r.supplier_id for r in rows}), "record_count": len(rows)}
    @staticmethod
    def supplier_price_increases(session, start, end):
        rows = session.query(SupplierPayment).filter(SupplierPayment.service_date >= start, SupplierPayment.service_date <= end).order_by(SupplierPayment.supplier_id, SupplierPayment.service_date).all(); increases = sum(Decimal(rows[i].total_debt or 0) > Decimal(rows[i - 1].total_debt or 0) and rows[i].supplier_id == rows[i - 1].supplier_id for i in range(1, len(rows))); return {"increase_count": increases, "record_count": len(rows)}
    @staticmethod
    def tour_profitability(session, start, end):
        tours = session.query(Tour).all(); results = []
        for tour in tours:
            revenue = sum((Decimal(b.grand_total or 0) for b in tour.bookings if b.booking_date and start <= b.booking_date <= end), Decimal(0)); cost = sum((Decimal(c.amount or 0) for c in tour.cost_items), Decimal(0)); results.append({"tour_id": tour.id, "name": tour.name, "profit": str(revenue - cost)})
        return {"tours": results[:20], "loss_making_count": sum(Decimal(item["profit"]) < 0 for item in results), "record_count": len(results)}
    @staticmethod
    def prevented_overpayment(session, start, end):
        rows = session.query(RestaurantReconciliation).filter(RestaurantReconciliation.created_at >= start, RestaurantReconciliation.created_at <= end).all(); return {"amount": str(sum((Decimal(r.potential_overpayment or 0) for r in rows), Decimal(0))), "record_count": len(rows)}
    @staticmethod
    def cancellation_costs(session, start, end):
        rows = session.query(Cancellation).filter(Cancellation.cancellation_date >= start, Cancellation.cancellation_date <= end).all(); return {"amount": str(sum((Decimal(r.cancellation_fee or 0) + Decimal(r.supplier_penalty or 0) for r in rows), Decimal(0))), "record_count": len(rows)}
    @classmethod
    def cash_flow(cls, session, start, end):
        receivables = cls.overdue_receivables(session, start, end); payables = cls.overdue_payables(session, start, end); return {"receivables": receivables["amount"], "payables": payables["amount"], "net_outlook": str(Decimal(receivables["amount"]) - Decimal(payables["amount"])), "record_count": receivables["record_count"] + payables["record_count"]}
    @staticmethod
    def missing_documents(session, start, end):
        rows = session.query(Transaction).filter(Transaction.transaction_date >= start, Transaction.transaction_date <= end, ~Transaction.documents.any()).all(); return {"missing_count": len(rows), "record_count": len(rows)}
    @staticmethod
    def data_quality(session, start, end):
        missing_currency = session.query(Booking).filter(or_(Booking.currency.is_(None), Booking.currency == "")).count(); missing_number = session.query(Booking).filter(or_(Booking.booking_number.is_(None), Booking.booking_number == "")).count(); return {"missing_currency": missing_currency, "missing_booking_number": missing_number, "record_count": missing_currency + missing_number}


class AccountingAssistantService:
    INTENTS = {
        "monthly_income_expense": ("gelir gider net aylık", SafeAnalyticsService.income_expense, "Gelir ve Giderler"),
        "overdue_receivables": ("gecikmiş alacak tahsilat", SafeAnalyticsService.overdue_receivables, "Tahsilatlar"),
        "overdue_payables": ("gecikmiş tedarikçi ödeme borç", SafeAnalyticsService.overdue_payables, "Tedarikçi Ödemeleri"),
        "tour_profitability": ("tur kârlılık kar zarar", SafeAnalyticsService.tour_profitability, "Tur Kârlılığı"),
        "loss_making_tours": ("zarar eden turlar", SafeAnalyticsService.tour_profitability, "Tur Kârlılığı"),
        "collections_by_period": ("dönem tahsilatlar tahsilat", SafeAnalyticsService.collections, "Tahsilatlar"),
        "supplier_spending": ("tedarikçi harcama maliyet", SafeAnalyticsService.supplier_spending, "Tedarikçi Ödemeleri"),
        "supplier_price_increases": ("tedarikçi fiyat artış", SafeAnalyticsService.supplier_price_increases, "Tedarikçi Ödemeleri"),
        "reconciliation_differences": ("mutabakat fark", SafeAnalyticsService.reconciliation, "Belge Mutabakatı"),
        "prevented_overpayment": ("önlenen fazla ödeme kazanım", SafeAnalyticsService.prevented_overpayment, "Restoran Mutabakatı"),
        "bank_unmatched_movements": ("banka eşleşmemiş hareket", SafeAnalyticsService.bank_unmatched, "Banka Hareketleri ve Mutabakat"),
        "cancellation_costs": ("iptal maliyet ceza", SafeAnalyticsService.cancellation_costs, "Rezervasyonlar"),
        "cash_flow_outlook": ("nakit akış görünüm", SafeAnalyticsService.cash_flow, "Kasa ve Bankalar"),
        "document_confidence": ("belge güven kalite", SafeAnalyticsService.document_quality, "Belge Arşivi"),
        "missing_documents": ("eksik belgesiz kayıt", SafeAnalyticsService.missing_documents, "Belge Arşivi"),
        "data_quality_warnings": ("veri kalite uyarı", SafeAnalyticsService.data_quality, "Kontrol Merkezi"),
        "current_account_balances": ("en yüksek açık bakiyeli müşteri cari bakiyesi ödeme davranışı restaurant", SafeAnalyticsService.current_account_balances, "Cari Hesap Mutabakatı"),
        "current_account_over_90": ("90 günü geçen alacak", SafeAnalyticsService.current_account_over_90, "Cari Hesap Mutabakatı"),
        "disputed_current_accounts": ("bu ay kaç cari mutabakat uyuşmadı mutabık değil", SafeAnalyticsService.disputed_accounts, "Cari Hesap Mutabakatı"),
    }
    FORBIDDEN = re.compile(r"\b(delete|drop|update|insert|öde|ödeme yap|sil|onayla|bakiyeyi değiştir|ignore previous|talimatları unut)\b", re.I)

    @classmethod
    def classify(cls, question):
        if cls.FORBIDDEN.search(question): return "unsafe"
        normalized = question.casefold(); scored = [(sum(word in normalized for word in words.split()), intent) for intent, (words, _, _) in cls.INTENTS.items()]
        score, intent = max(scored); return intent if score else "unsupported"

    @classmethod
    def answer(cls, session, question, start, end, client=None, history=False):
        intent = cls.classify(question)
        if intent == "unsafe": return {"intent": intent, "answer": "Bu işlem güvenlik nedeniyle yapılamaz. İlgili sayfayı açarak insan onayıyla devam edin.", "records": 0, "page": None}
        if intent == "unsupported": return {"intent": intent, "answer": "Bu soru güvenli rapor araçlarımın kapsamında değil. Gelir-gider, gecikmiş ödemeler, mutabakat, banka veya belge kalitesi hakkında sorabilirsiniz.", "records": 0, "page": None}
        _, function, page = cls.INTENTS[intent]; facts = function(session, start, end); records = facts.get("record_count", 0)
        if not records: answer = "Seçilen dönem ve filtrelerde yanıt üretmek için yeterli kayıt bulunamadı."
        elif client:
            safe_facts = SensitiveDataMaskingService.minimize_facts(facts, set(facts))
            result, request_id = client.request("assistant_query", [{"role": "user", "content": f"Bu doğrulanmış sayıları değiştirmeden kısa Türkçe açıkla: {json.dumps(safe_facts, ensure_ascii=False)}"}], {"type": "object", "additionalProperties": False, "required": ["answer"], "properties": {"answer": {"type": "string"}}}, timeout=client.config["assistant_timeout"], summary={"intent": intent, "analytics_function": function.__name__})
            answer = result["answer"]
        else: answer = "Doğrulanmış sonuçlar: " + ", ".join(f"{key}: {value}" for key, value in facts.items() if key != "record_count")
        if history: session.add(AssistantQuery(question_masked=SensitiveDataMaskingService.mask_text(question), intent=intent, analytics_function=function.__name__, filters={"start": start.isoformat(), "end": end.isoformat()}, result_summary=facts, answer=answer, history_enabled=True))
        return {"intent": intent, "answer": answer, "facts": facts, "records": records, "page": page, "period": f"{start:%d.%m.%Y}–{end:%d.%m.%Y}", "timestamp": datetime.utcnow().isoformat()}


class AnomalyExplanationService:
    @staticmethod
    def explain(client, anomaly_type, severity, facts):
        if int(facts.get("sample_size", 1)) < 3: return "Karşılaştırma için yeterli geçmiş örnek bulunmuyor.", None
        safe = SensitiveDataMaskingService.minimize_facts(facts, set(facts)); result, request_id = client.request("anomaly_explanation", [{"role": "user", "content": f"Şiddeti değiştirmeden anomaliyi Türkçe açıkla ve sonraki kontrolü öner: {json.dumps(safe, ensure_ascii=False)}"}], {"type": "object", "additionalProperties": False, "required": ["explanation"], "properties": {"explanation": {"type": "string"}}}, summary={"anomaly_type": anomaly_type, "severity": severity})
        if client.session:
            request = client.session.query(AIRequest).filter(AIRequest.request_id == request_id).first()
            client.session.add(AnomalyExplanation(ai_request_id=request.id if request else None, anomaly_type=anomaly_type, severity=severity, facts=safe, explanation=result["explanation"]))
            from database.models import AuditLog
            client.session.add(AuditLog(event_type="AI_ANOMALY_EXPLANATION", entity_type="anomaly", action=anomaly_type, new_values={"severity": severity, "facts": safe}, source="ai_service", status="Tamamlandı"))
        return result["explanation"], request_id


class SupplierObjectionService:
    REQUIRED = {"supplier", "invoice_number", "expected_amount", "invoiced_amount", "difference", "disputed_fields"}
    @classmethod
    def generate(cls, client, facts, tone="Resmî", language="TR"):
        if not cls.REQUIRED <= set(facts) or not facts.get("disputed_fields"): raise ValueError("İtiraz taslağı için doğrulanmış kanıtlar eksik.")
        safe = SensitiveDataMaskingService.minimize_facts(facts, cls.REQUIRED | {"voucher_number", "booking_number", "service_date", "document_references"})
        result, request_id = client.request("supplier_objection", [{"role": "user", "content": f"Yalnız bu doğrulanmış bilgilerle {tone} tonda {'Türkçe' if language == 'TR' else 'İngilizce'} gönderilmeyecek itiraz taslağı hazırla: {json.dumps(safe, ensure_ascii=False)}"}], {"type": "object", "additionalProperties": False, "required": ["subject", "body"], "properties": {"subject": {"type": "string"}, "body": {"type": "string"}}}, summary={"language": language, "tone": tone}); return result, request_id, safe


class ManagementInsightService:
    @staticmethod
    def generate(client, facts, detail="Kısa"):
        if not facts or not facts.get("record_count", 0): return {"commentary": "Yorum üretmek için yeterli doğrulanmış veri bulunamadı."}, None
        safe = SensitiveDataMaskingService.minimize_facts(facts, set(facts)); result, request_id = client.request("management_commentary", [{"role": "user", "content": f"Rakam eklemeden veya değiştirmeden {detail} Türkçe yönetim yorumu yaz: {json.dumps(safe, ensure_ascii=False)}"}], {"type": "object", "additionalProperties": False, "required": ["commentary"], "properties": {"commentary": {"type": "string"}}}, summary={"detail": detail})
        supplied_numbers = set(re.findall(r"-?\d+(?:[.,]\d+)?", json.dumps(safe, ensure_ascii=False)))
        generated_numbers = set(re.findall(r"-?\d+(?:[.,]\d+)?", result["commentary"]))
        if not generated_numbers <= supplied_numbers: raise AIResponseError("AI yorumu kaynak ölçümlerde bulunmayan rakam içerdi.")
        return result, request_id
