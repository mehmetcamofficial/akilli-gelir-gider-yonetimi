import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from database.models import (
    Booking, Collection, Document, Supplier, SupplierPayment, Tour, Transaction,
    Voucher,
)


EXTRACTION_FIELDS = [
    "document_type", "supplier_name", "invoice_number", "document_date",
    "voucher_number", "booking_number", "tour_name", "service_date",
    "passenger_count", "adult_count", "child_count", "guide_count", "driver_count",
    "free_person_count", "currency", "unit_price",
    "subtotal", "tax_amount", "grand_total", "paid_amount", "remaining_amount",
    "payment_method", "notes", "additional_charges", "discounts", "tax_rate",
    "confidence", "unreadable_fields",
]
DOCUMENT_TYPES = [
    "supplier_invoice", "restaurant_invoice", "receipt", "pos_slip", "voucher",
    "payment_receipt", "hotel_invoice", "transfer_invoice", "guide_expense_document",
]


class AIExtractionError(RuntimeError):
    pass


class SensitiveDataMaskingService:
    PATTERNS = [
        (re.compile(r"\b\d{11}\b"), "[TCKN_MASKELENDI]"),
        (re.compile(r"\b[A-Z0-9]{6,12}\b(?=\s*(?:pasaport|passport))", re.I), "[PASAPORT_MASKELENDI]"),
        (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[KART_MASKELENDI]"),
        (re.compile(r"\bTR\d{2}[A-Z0-9]{5}[A-Z0-9]{16}\b", re.I), lambda m: f"{m.group(0)[:6]}…{m.group(0)[-4:]}"),
    ]

    @classmethod
    def mask_text(cls, value):
        text = str(value or "")
        for pattern, replacement in cls.PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    @classmethod
    def minimal_context(cls, context):
        allowed = {"booking_number", "voucher_number", "tour_name", "supplier_name"}
        return {key: cls.mask_text(value) for key, value in (context or {}).items() if key in allowed}


class OpenRouterDocumentExtractor:
    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    MODEL = "openai/gpt-4o-mini"

    def __init__(self, api_key, transport=None):
        if not api_key:
            raise AIExtractionError("OpenRouter API anahtarı bulunamadı. Manuel giriş kullanabilirsiniz.")
        self.api_key = api_key
        self.transport = transport or self._post

    @staticmethod
    def schema():
        string_fields = {
            key: {"type": ["string", "null"]}
            for key in (
                "document_type", "supplier_name", "invoice_number", "document_date",
                "voucher_number", "booking_number", "tour_name", "service_date",
                "currency", "payment_method", "notes",
            )
        }
        properties = dict(string_fields)
        for key in ("passenger_count", "adult_count", "child_count", "guide_count", "driver_count", "free_person_count"):
            properties[key] = {"type": ["integer", "null"]}
        for key in ("unit_price", "subtotal", "tax_amount", "grand_total", "paid_amount", "remaining_amount", "additional_charges", "discounts", "tax_rate"):
            properties[key] = {"type": ["number", "null"]}
        properties["confidence"] = {"type": "number", "minimum": 0, "maximum": 1}
        properties["unreadable_fields"] = {"type": "array", "items": {"type": "string"}}
        properties["document_type"] = {"type": ["string", "null"], "enum": DOCUMENT_TYPES + [None]}
        return {"type": "object", "properties": properties, "required": EXTRACTION_FIELDS, "additionalProperties": False}

    def extract(self, file_bytes, filename, mime_type, context=None):
        prompt = (
            "Bu turizm muhasebe belgesini yalnızca sınıflandır ve görünen alanları çıkar. "
            "Tahmin etme; okunamayan alanları unreadable_fields listesine ekle. "
            "Muhasebe kararı verme. Gereksiz kişisel veri döndürme. Bağlam: "
            + json.dumps(SensitiveDataMaskingService.minimal_context(context), ensure_ascii=False)
        )
        if mime_type == "application/pdf":
            try:
                import fitz
                pdf = fitz.open(stream=file_bytes, filetype="pdf")
                local_text = "\n".join(page.get_text("text") for page in pdf)
            except Exception as exc:
                raise AIExtractionError("PDF metni güvenli biçimde yerel olarak okunamadı. Manuel giriş kullanabilirsiniz.") from exc
            if not local_text.strip():
                raise AIExtractionError("Taranmış PDF kişisel veriler maskelenmeden AI'ya gönderilmedi. Manuel giriş kullanabilirsiniz.")
            media = {"type": "text", "text": "Maskelenmiş belge metni:\n" + SensitiveDataMaskingService.mask_text(local_text)[:50000]}
        else:
            raise AIExtractionError("Görsel belge kişisel veriler yerel olarak maskelenemediği için AI'ya gönderilmedi. Manuel giriş kullanabilirsiniz.")
        payload = {
            "model": self.MODEL,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, media]}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "tourism_document_extraction", "strict": True, "schema": self.schema()}},
            "temperature": 0,
        }
        response = self.transport(payload)
        try:
            content = response["choices"][0]["message"]["content"]
            result = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIExtractionError("AI geçerli yapılandırılmış JSON döndürmedi. Manuel giriş kullanabilirsiniz.") from exc
        self._validate(result)
        return result

    def _post(self, payload):
        request = urllib.request.Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AIExtractionError("AI servisine ulaşılamadı. Manuel giriş ile devam edebilirsiniz.") from exc

    @staticmethod
    def _validate(result):
        if not isinstance(result, dict) or set(result) != set(EXTRACTION_FIELDS):
            raise AIExtractionError("AI yanıt şeması geçersiz. Manuel giriş kullanabilirsiniz.")
        confidence = result.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise AIExtractionError("AI güven skoru geçersiz.")
        if not isinstance(result.get("unreadable_fields"), list):
            raise AIExtractionError("AI okunamayan alan listesini geçersiz döndürdü.")


class DocumentMatchingService:
    @staticmethod
    def find_matches(session, extracted):
        matches = []
        def add(entity_type, rows, score):
            for row in rows:
                matches.append({"entity_type": entity_type, "entity_id": row.id, "score": score, "record": row})

        if extracted.get("voucher_number"):
            add("voucher", session.query(Voucher).filter(Voucher.voucher_number == extracted["voucher_number"]).all(), 100)
            add("booking", session.query(Booking).filter(Booking.voucher_number == extracted["voucher_number"]).all(), 95)
        if extracted.get("booking_number"):
            add("booking", session.query(Booking).filter(Booking.booking_number == extracted["booking_number"]).all(), 100)
        if extracted.get("tour_name"):
            add("tour", session.query(Tour).filter(func.lower(Tour.name) == extracted["tour_name"].lower()).all(), 90)
        if extracted.get("supplier_name"):
            add("supplier", session.query(Supplier).filter(func.lower(Supplier.name) == extracted["supplier_name"].lower()).all(), 90)
        if extracted.get("invoice_number"):
            add("invoice", session.query(Transaction).filter(Transaction.invoice_number == extracted["invoice_number"]).all(), 100)
            add("supplier_payment", session.query(SupplierPayment).filter(SupplierPayment.invoice_reference == extracted["invoice_number"]).all(), 95)
        unique = {}
        for match in matches:
            key = (match["entity_type"], match["entity_id"])
            if key not in unique or match["score"] > unique[key]["score"]:
                unique[key] = match
        return sorted(unique.values(), key=lambda item: item["score"], reverse=True)

    @staticmethod
    def agency_record(match, session):
        if not match:
            return {}
        record, kind = match["record"], match["entity_type"]
        if kind == "voucher":
            booking = session.get(Booking, record.booking_id)
        elif kind == "booking":
            booking = record
        else:
            booking = None
        tour = booking.tour if booking else (record if kind == "tour" else None)
        supplier = record if kind == "supplier" else None
        payment = record if kind == "supplier_payment" else None
        invoice = record if kind == "invoice" else None
        return {
            "voucher_number": getattr(record, "voucher_number", None) or getattr(booking, "voucher_number", None),
            "booking_number": getattr(booking, "booking_number", None),
            "tour_name": getattr(tour, "name", None),
            "supplier_name": getattr(supplier, "name", None),
            "service_date": getattr(booking, "service_start_date", None) or getattr(payment, "service_date", None),
            "passenger_count": getattr(booking, "passenger_count", None),
            "adult_count": getattr(booking, "adult_count", None),
            "child_count": getattr(booking, "child_count", None),
            "guide_count": 0,
            "driver_count": 0,
            "free_person_count": 0,
            "currency": getattr(booking, "currency", None) or getattr(payment, "currency", None) or getattr(invoice, "currency", None),
            "unit_price": getattr(booking, "unit_price", None),
            "subtotal": getattr(invoice, "subtotal", None) or getattr(booking, "total_price", None),
            "tax_amount": getattr(invoice, "tax_total", None) or getattr(booking, "tax_amount", None),
            "grand_total": getattr(invoice, "grand_total", None) or getattr(payment, "total_debt", None) or getattr(booking, "grand_total", None),
            "paid_amount": getattr(invoice, "paid_amount", None) or getattr(payment, "paid_amount", None) or getattr(booking, "collected_total", None),
            "remaining_amount": getattr(invoice, "remaining_amount", None) or getattr(payment, "remaining_amount", None) or getattr(booking, "remaining_amount", None),
            "payment_method": getattr(payment, "payment_method", None) or getattr(booking, "payment_method", None),
            "notes": getattr(payment, "notes", None) or getattr(booking, "notes", None),
            "booking_status": getattr(booking, "booking_status", None),
        }


class ReconciliationEngine:
    def __init__(self, amount_tolerance=Decimal("1.00"), percentage_tolerance=Decimal("0.5"), passenger_tolerance=0, date_tolerance=1):
        self.amount_tolerance = Decimal(str(amount_tolerance))
        self.percentage_tolerance = Decimal(str(percentage_tolerance))
        self.passenger_tolerance = int(passenger_tolerance)
        self.date_tolerance = int(date_tolerance)

    @staticmethod
    def _decimal(value):
        try:
            return Decimal(str(value)) if value not in (None, "") else None
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _date(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            return None

    def reconcile(self, document, agency, matched_entity_type=None, matched_entity_id=None, duplicate_document=False, duplicate_invoice=False):
        if not agency:
            return self._result("Eşleşen Kayıt Bulunamadı", "yüksek", matched_entity_type, matched_entity_id, [], None, document.get("grand_total"), "İlgili kaydı manuel seçin.")
        differences = []
        def text_check(field, label):
            left, right = document.get(field), agency.get(field)
            if left and right and str(left).strip().casefold() != str(right).strip().casefold():
                differences.append({"field": field, "label": label, "document": left, "agency": right, "severity": "yüksek"})
        for field, label in (("voucher_number", "Voucher"), ("booking_number", "Rezervasyon"), ("supplier_name", "Tedarikçi"), ("currency", "Para birimi")):
            text_check(field, label)
        doc_date, agency_date = self._date(document.get("service_date")), self._date(agency.get("service_date"))
        if doc_date and agency_date and abs((doc_date - agency_date).days) > self.date_tolerance:
            differences.append({"field": "service_date", "label": "Hizmet tarihi", "document": str(doc_date), "agency": str(agency_date), "severity": "orta"})
        for field, label in (("passenger_count", "Yolcu"), ("adult_count", "Yetişkin"), ("child_count", "Çocuk"), ("guide_count", "Rehber"), ("driver_count", "Şoför"), ("free_person_count", "Ücretsiz kişi")):
            if document.get(field) is not None and agency.get(field) is not None and abs(int(document[field]) - int(agency[field])) > self.passenger_tolerance:
                differences.append({"field": field, "label": label, "document": document[field], "agency": agency[field], "severity": "yüksek"})
        for field, label in (("unit_price", "Birim fiyat"), ("subtotal", "Ara toplam"), ("tax_amount", "Vergi"), ("grand_total", "Toplam"), ("paid_amount", "Önceki ödeme"), ("remaining_amount", "Kalan bakiye")):
            left, right = self._decimal(document.get(field)), self._decimal(agency.get(field))
            if left is not None and right is not None and abs(left - right) > self.amount_tolerance:
                differences.append({"field": field, "label": label, "document": float(left), "agency": float(right), "severity": "yüksek" if field in {"grand_total", "currency"} else "orta"})
        paying_count = (document.get("passenger_count") or 0) - (document.get("free_person_count") or 0)
        unit_price = self._decimal(agency.get("unit_price") or document.get("unit_price"))
        additions = self._decimal(document.get("additional_charges")) or Decimal(0)
        discounts = self._decimal(document.get("discounts")) or Decimal(0)
        calculated_subtotal = Decimal(paying_count) * unit_price + additions - discounts if unit_price is not None else None
        document_subtotal = self._decimal(document.get("subtotal"))
        if calculated_subtotal is not None and document_subtotal is not None and abs(calculated_subtotal - document_subtotal) > self.amount_tolerance:
            differences.append({"field": "subtotal_calculation", "label": "Ara toplam hesabı", "document": float(document_subtotal), "agency": float(calculated_subtotal), "severity": "yüksek"})
        document_tax = self._decimal(document.get("tax_amount"))
        tax_rate = self._decimal(document.get("tax_rate"))
        if document_subtotal is not None and document_tax is not None and tax_rate is not None:
            calculated_tax = document_subtotal * tax_rate / Decimal(100)
            if abs(calculated_tax - document_tax) > self.amount_tolerance:
                differences.append({"field": "tax_calculation", "label": "KDV hesabı", "document": float(document_tax), "agency": float(calculated_tax), "severity": "yüksek"})
        document_total = self._decimal(document.get("grand_total"))
        if document_subtotal is not None and document_tax is not None and document_total is not None and abs(document_subtotal + document_tax - document_total) > self.amount_tolerance:
            differences.append({"field": "total_calculation", "label": "Genel toplam hesabı", "document": float(document_total), "agency": float(document_subtotal + document_tax), "severity": "yüksek"})
        if duplicate_document:
            differences.append({"field": "document_hash", "label": "Mükerrer belge", "document": "Aynı dosya mevcut", "agency": "Tekil olmalı", "severity": "kritik"})
        if duplicate_invoice:
            differences.append({"field": "invoice_number", "label": "Mükerrer fatura", "document": document.get("invoice_number"), "agency": "Numara daha önce kullanılmış", "severity": "kritik"})
        if agency.get("booking_status") and "iptal" in agency["booking_status"].casefold() and self._decimal(document.get("grand_total")) not in (None, Decimal("0")):
            differences.append({"field": "cancelled_passenger", "label": "İptal yolcu faturalandı", "document": document.get("grand_total"), "agency": agency["booking_status"], "severity": "kritik"})
        for key, label in (("free_allowance_expected", "Ücretsiz rehber/sürücü hakkı eksik"), ("agreed_supplier_price", "Anlaşılan tedarikçi fiyatı aşıldı")):
            if key == "free_allowance_expected" and agency.get(key) and not document.get(key):
                differences.append({"field": key, "label": label, "document": "Yok", "agency": "Var", "severity": "orta"})
            if key == "agreed_supplier_price":
                agreed, total = self._decimal(agency.get(key)), self._decimal(document.get("grand_total"))
                if agreed is not None and total is not None and total > agreed + self.amount_tolerance:
                    differences.append({"field": key, "label": label, "document": float(total), "agency": float(agreed), "severity": "yüksek"})
        confidence = float(document.get("confidence") or 0)
        if confidence < 0.60:
            differences.append({"field": "confidence", "label": "Düşük AI güveni", "document": confidence, "agency": ">= 0.60", "severity": "orta"})
        expected, actual = self._decimal(agency.get("grand_total")), self._decimal(document.get("grand_total"))
        if not differences:
            status, severity = "Tam Eşleşti", "düşük"
        elif any(item["severity"] == "kritik" for item in differences):
            status, severity = "Kritik Uyumsuzluk", "kritik"
        else:
            amount_diff = abs((actual or Decimal(0)) - (expected or Decimal(0)))
            pct = amount_diff / abs(expected) * 100 if expected else Decimal(0)
            if all(item["severity"] != "yüksek" for item in differences) and amount_diff <= self.amount_tolerance and pct <= self.percentage_tolerance:
                status, severity = "Küçük Fark Var", "düşük"
            else:
                status, severity = "İnceleme Gerekli", "orta"
        return self._result(status, severity, matched_entity_type, matched_entity_id, differences, expected, actual, "Farkları kontrol edin; nihai karar için kullanıcı onayı gerekir.")

    @staticmethod
    def _result(status, severity, entity_type, entity_id, differences, expected, actual, action):
        difference = (actual or Decimal(0)) - (expected or Decimal(0)) if expected is not None or actual is not None else Decimal(0)
        percentage = difference / abs(expected) * 100 if expected else Decimal(0)
        return {"status": status, "severity": severity, "matched_entity_type": entity_type, "matched_entity_id": entity_id, "field_differences": differences, "expected_total": float(expected) if expected is not None else None, "document_total": float(actual) if actual is not None else None, "difference_amount": float(difference), "difference_percentage": float(percentage), "recommended_action": action}


class ReconciliationExplanationService:
    @staticmethod
    def explain(result):
        if not result["field_differences"]:
            return "Belgedeki kontrol edilen alanlar acente kaydıyla toleranslar içinde eşleşiyor."
        details = "; ".join(f"{item['label']}: belgede {item['document']}, kayıtta {item['agency']}" for item in result["field_differences"])
        return f"{result['status']}. Tespit edilen farklar: {details}. Nihai muhasebe kararı kullanıcıya aittir."
