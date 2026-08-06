import hashlib
import json
import re
import unicodedata
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path

import pandas as pd
from sqlalchemy import func

from database.models import (
    AuditLog, BankTransaction, Booking, Collection, Customer, ImportBatch,
    Supplier, SupplierPayment, Tour, Transaction, Voucher,
)


DATASET_TYPES = ["Gelir-Gider", "Rezervasyon", "Tahsilat", "Tedarikçi Ödemesi", "Fatura", "Tur", "Müşteri", "Tedarikçi", "Restoran Mutabakatı", "Voucher", "Banka Hareketleri", "Bilinmeyen"]
TARGET_FIELDS = {
    "transaction_date": "Tarih", "transaction_type": "İşlem Türü", "description": "Açıklama",
    "document_number": "Belge No", "invoice_number": "Fatura No", "booking_number": "Rezervasyon No",
    "voucher_number": "Voucher No", "tour_name": "Tur Adı", "tour_code": "Tur Kodu",
    "customer_name": "Müşteri", "supplier_name": "Tedarikçi", "restaurant_name": "Restoran",
    "hotel_name": "Otel", "guide_name": "Rehber", "passenger_count": "Yolcu Sayısı",
    "adult_count": "Yetişkin Sayısı", "child_count": "Çocuk Sayısı", "currency": "Para Birimi",
    "exchange_rate": "Döviz Kuru", "unit_price": "Birim Fiyat", "subtotal": "Ara Toplam",
    "tax_total": "KDV", "grand_total": "Genel Toplam", "collected_amount": "Tahsil Edilen",
    "paid_amount": "Ödenen", "remaining_amount": "Kalan", "income": "Gelir", "expense": "Gider",
    "debit": "Borç", "credit": "Alacak", "payment_status": "Ödeme Durumu",
    "payment_method": "Ödeme Yöntemi", "due_date": "Vade Tarihi", "service_date": "Hizmet Tarihi",
    "notes": "Notlar", "start_location": "Başlangıç Noktası", "end_location": "Bitiş Noktası",
    "capacity": "Kapasite", "email": "E-posta", "phone": "Telefon", "tax_number": "Vergi No",
}
ALIASES = {
    "transaction_date": ["tarih", "date", "islem tarihi", "belge tarihi", "booking date"],
    "transaction_type": ["islem turu", "type", "transaction type"],
    "description": ["aciklama", "description", "detail", "memo"],
    "document_number": ["belge no", "document no", "reference no", "referans"],
    "invoice_number": ["fatura no", "invoice no", "invoice number", "fatura numarasi"],
    "booking_number": ["rezervasyon no", "booking no", "reservation no", "booking number"],
    "voucher_number": ["voucher", "voucher no", "voucher number"],
    "tour_name": ["tur adi", "tour name", "tour"], "tour_code": ["tur kodu", "tour code"],
    "customer_name": ["musteri", "customer", "guest", "misafir", "client"],
    "supplier_name": ["tedarikci", "supplier", "vendor"], "restaurant_name": ["restoran", "restaurant"],
    "hotel_name": ["otel", "hotel"], "guide_name": ["rehber", "guide"],
    "passenger_count": ["yolcu sayisi", "kisi", "pax", "passenger count", "guest count"],
    "adult_count": ["yetiskin", "adult", "adult count"], "child_count": ["cocuk", "child", "child count"],
    "currency": ["para birimi", "currency", "doviz", "curr"], "exchange_rate": ["doviz kuru", "exchange rate", "kur"],
    "unit_price": ["birim fiyat", "unit price", "price"], "subtotal": ["ara toplam", "subtotal", "net total"],
    "tax_total": ["kdv", "vat", "tax", "vergi"], "grand_total": ["genel toplam", "grand total", "total", "tutar", "amount"],
    "collected_amount": ["tahsil edilen", "tahsilat", "collected", "collection amount"],
    "paid_amount": ["odenen", "paid", "payment amount"], "remaining_amount": ["kalan", "remaining", "balance"],
    "income": ["gelir", "income", "credit"], "expense": ["gider", "expense", "debit"],
    "debit": ["borc", "debit"], "credit": ["alacak", "credit"],
    "payment_status": ["odeme durumu", "payment status", "status"], "payment_method": ["odeme yontemi", "payment method", "method"],
    "due_date": ["vade tarihi", "due date", "payment date"], "service_date": ["hizmet tarihi", "service date", "travel date"],
    "notes": ["not", "notlar", "notes", "remarks"], "start_location": ["baslangic noktasi", "departure", "from"],
    "end_location": ["bitis noktasi", "arrival", "to"], "capacity": ["kapasite", "capacity"],
    "email": ["email", "e posta", "mail"], "phone": ["telefon", "phone", "mobile"], "tax_number": ["vergi no", "tax number", "vkn"],
}
REQUIRED_FIELDS = {
    "Gelir-Gider": {"transaction_date"}, "Rezervasyon": {"booking_number", "customer_name"},
    "Tahsilat": {"booking_number", "collected_amount"}, "Tedarikçi Ödemesi": {"supplier_name", "grand_total"},
    "Fatura": {"invoice_number", "grand_total"}, "Tur": {"tour_code", "tour_name"},
    "Müşteri": {"customer_name"}, "Tedarikçi": {"supplier_name"},
    "Restoran Mutabakatı": {"voucher_number", "grand_total"},
    "Voucher": {"voucher_number", "booking_number"}, "Banka Hareketleri": {"transaction_date"},
}
AMOUNT_FIELDS = {"unit_price", "subtotal", "tax_total", "grand_total", "collected_amount", "paid_amount", "remaining_amount", "income", "expense", "debit", "credit", "exchange_rate"}
INTEGER_FIELDS = {"passenger_count", "adult_count", "child_count", "capacity"}
DATE_FIELDS = {"transaction_date", "due_date", "service_date"}


def normalize_column_name(value):
    text = str(value or "").strip().lower().translate(str.maketrans("çğıöşü", "cgiosu"))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


class ExcelFileReader:
    @staticmethod
    def sheet_names(file_bytes, filename):
        if Path(filename).suffix.lower() == ".csv": return ["CSV"]
        return pd.ExcelFile(BytesIO(file_bytes), engine="xlrd" if filename.lower().endswith(".xls") else "openpyxl").sheet_names

    @staticmethod
    def raw_sheet(file_bytes, filename, sheet_name=None):
        if Path(filename).suffix.lower() == ".csv":
            for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin1"):
                try: return pd.read_csv(BytesIO(file_bytes), header=None, sep=None, engine="python", encoding=encoding)
                except UnicodeDecodeError: continue
            raise ValueError("CSV karakter kodlaması okunamadı.")
        selected_sheet = 0 if sheet_name is None else sheet_name
        return pd.read_excel(BytesIO(file_bytes), sheet_name=selected_sheet, header=None, engine="xlrd" if filename.lower().endswith(".xls") else "openpyxl")

    @classmethod
    def analyze(cls, file_bytes, filename, sheet_name=None):
        raw = cls.raw_sheet(file_bytes, filename, sheet_name)
        header_index = HeaderDetectionService.detect(raw)
        headers = ColumnDetectionService.unique_headers(raw.iloc[header_index].tolist())
        cleaned = raw.iloc[header_index + 1:].copy(); cleaned.columns = headers
        cleaned = cleaned.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
        return cleaned, header_index


class ExcelImportService:
    get_sheet_names = staticmethod(ExcelFileReader.sheet_names)
    @staticmethod
    def load_dataframe(file_bytes, filename, sheet_name=None): return ExcelFileReader.analyze(file_bytes, filename, sheet_name)[0]


class HeaderDetectionService:
    @staticmethod
    def detect(raw, scan_rows=15):
        best_index, best_score = 0, -1
        for index in range(min(scan_rows, len(raw))):
            values = [value for value in raw.iloc[index].tolist() if pd.notna(value) and str(value).strip()]
            strings = sum(isinstance(value, str) for value in values)
            unique = len({normalize_column_name(value) for value in values})
            mapped = sum(ColumnDetectionService.best_match(value)[1] >= 0.72 for value in values)
            score = len(values) + strings * 1.5 + unique * 0.2 + mapped * 3
            if len(values) >= 2 and score > best_score: best_index, best_score = index, score
        return best_index


class ColumnDetectionService:
    @staticmethod
    def unique_headers(values):
        result, counts = [], {}
        for index, value in enumerate(values):
            base = str(value).strip() if pd.notna(value) and str(value).strip() else f"Adsız Kolon {index + 1}"
            counts[base] = counts.get(base, 0) + 1
            result.append(base if counts[base] == 1 else f"{base} ({counts[base]})")
        return result

    @staticmethod
    def best_match(source):
        normalized = normalize_column_name(source); best, score = None, 0.0
        for target, aliases in ALIASES.items():
            for alias in aliases + [TARGET_FIELDS[target]]:
                candidate = normalize_column_name(alias)
                current = 1.0 if normalized == candidate else SequenceMatcher(None, normalized, candidate).ratio()
                if candidate in normalized or normalized in candidate: current = max(current, 0.88)
                if current > score: best, score = target, current
        return (best, round(score, 2)) if score >= 0.58 else (None, 0.0)


class ColumnMappingService:
    @classmethod
    def analyze(cls, columns):
        return {str(column): {"target": ColumnDetectionService.best_match(column)[0], "confidence": ColumnDetectionService.best_match(column)[1]} for column in columns}

    @classmethod
    def guess(cls, columns, field_keys):
        analysis = cls.analyze(columns); result = {field: "<Boş>" for field in field_keys}
        for source, item in analysis.items():
            if item["target"] in result and item["confidence"] >= 0.72 and result[item["target"]] == "<Boş>": result[item["target"]] = source
        return result


class AIColumnLabelingService:
    """Optional helper for ambiguous labels; it never validates or imports data."""

    @staticmethod
    def _mask(value):
        text = str(value or "")
        text = re.sub(r"\b\d{11}\b", "[KIMLIK_MASKELENDI]", text)
        text = re.sub(r"\b[A-Z0-9]{6,12}\b", "[BELGE_MASKELENDI]", text, flags=re.I)
        text = re.sub(r"\bTR\d{24}\b", "TR**********************", text, flags=re.I)
        text = re.sub(r"\b(?:\d[ -]*?){13,19}\b", "[KART_MASKELENDI]", text)
        return text[:120]

    @classmethod
    def suggest(cls, api_key, dataframe, ambiguous_columns):
        columns = [column for column in ambiguous_columns if column in dataframe.columns]
        samples = {
            str(column): [cls._mask(value) for value in dataframe[column].dropna().head(5).tolist()]
            for column in columns
        }
        schema = {
            "name": "column_suggestions",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "suggestions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "target": {"type": ["string", "null"], "enum": list(TARGET_FIELDS) + [None]},
                                "explanation": {"type": "string"},
                            },
                            "required": ["source", "target", "explanation"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["suggestions"],
                "additionalProperties": False,
            },
        }
        body = json.dumps({
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "Yalnızca belirsiz Excel kolonlarını muhasebe alanlarıyla öneri olarak eşleştir. Finansal karar verme. Veri: " + json.dumps(samples, ensure_ascii=False)}],
            "response_format": {"type": "json_schema", "json_schema": schema},
            "temperature": 0,
        }).encode("utf-8")
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return json.loads(payload["choices"][0]["message"]["content"])["suggestions"]


class DatasetTypeClassifier:
    SIGNALS = {
        "Rezervasyon": {"booking_number", "customer_name", "passenger_count"}, "Tahsilat": {"booking_number", "collected_amount"},
        "Tedarikçi Ödemesi": {"supplier_name", "paid_amount", "due_date"}, "Fatura": {"invoice_number", "tax_total", "grand_total"},
        "Tur": {"tour_code", "tour_name", "capacity"}, "Müşteri": {"customer_name", "email", "phone"},
        "Tedarikçi": {"supplier_name", "tax_number", "email"}, "Restoran Mutabakatı": {"restaurant_name", "voucher_number", "passenger_count"},
        "Voucher": {"voucher_number", "booking_number", "service_date"}, "Banka Hareketleri": {"debit", "credit", "transaction_date"},
        "Gelir-Gider": {"income", "expense", "transaction_type", "grand_total"},
    }
    @classmethod
    def classify(cls, mapping):
        targets = {item["target"] for item in mapping.values() if item["target"]}
        scored = [(kind, len(targets & signals) / len(signals)) for kind, signals in cls.SIGNALS.items()]
        kind, score = max(scored, key=lambda item: item[1])
        return (kind if score >= 0.34 else "Bilinmeyen", round(score, 2))


class ValueNormalizationService:
    CURRENCY = {"tl": "TRY", "try": "TRY", "₺": "TRY", "eur": "EUR", "€": "EUR", "usd": "USD", "$": "USD", "gbp": "GBP", "£": "GBP"}
    STATUS = {"odendi": "Ödendi", "paid": "Ödendi", "tamamlandi": "Ödendi", "evet": "Evet", "hayir": "Hayır", "bekliyor": "Beklemede", "pending": "Beklemede", "kismi": "Kısmen Ödendi", "partial": "Kısmen Ödendi"}
    @staticmethod
    def decimal(value):
        if value is None or pd.isna(value) or str(value).strip() == "": return None
        text = re.sub(r"[^0-9,\.\-]", "", str(value).strip())
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
        elif "," in text: text = text.replace(".", "").replace(",", ".")
        try: return Decimal(text).quantize(Decimal("0.01"))
        except InvalidOperation: return None
    @staticmethod
    def date(value):
        if value is None or pd.isna(value) or str(value).strip() == "": return None
        if isinstance(value, (int, float)) and 1 < float(value) < 100000: return pd.Timestamp("1899-12-30") + pd.to_timedelta(float(value), unit="D")
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce"); return None if pd.isna(parsed) else parsed.to_pydatetime()
    @classmethod
    def currency(cls, value):
        normalized = normalize_column_name(value); return cls.CURRENCY.get(normalized) or cls.CURRENCY.get(str(value).strip()) or (str(value).strip().upper() if str(value).strip().upper() in {"TRY", "EUR", "USD", "GBP"} else None)
    @classmethod
    def status(cls, value): return cls.STATUS.get(normalize_column_name(value), str(value).strip() if value is not None else None)
    @classmethod
    def row(cls, source_row, mapping):
        result = {}
        for source, target in mapping.items():
            if not target or target == "Kullanma": continue
            value = source_row.get(source)
            if target in AMOUNT_FIELDS: value = cls.decimal(value)
            elif target in INTEGER_FIELDS:
                try: value = int(float(value)) if pd.notna(value) else None
                except (TypeError, ValueError): value = None
            elif target in DATE_FIELDS: value = cls.date(value)
            elif target == "currency": value = cls.currency(value)
            elif target == "payment_status": value = cls.status(value)
            elif pd.isna(value): value = None
            else: value = str(value).strip()
            result[target] = value
        return result


class DuplicateDetectionService:
    @staticmethod
    def check(session, dataset_type, row):
        if row.get("invoice_number") and session.query(Transaction).filter(Transaction.invoice_number == row["invoice_number"]).first(): return "Fatura numarası mevcut"
        if row.get("voucher_number") and (session.query(Voucher).filter(Voucher.voucher_number == row["voucher_number"]).first() or session.query(Booking).filter(Booking.voucher_number == row["voucher_number"]).first()): return "Voucher numarası mevcut"
        if row.get("booking_number") and dataset_type == "Rezervasyon" and session.query(Booking).filter(Booking.booking_number == row["booking_number"]).first(): return "Rezervasyon numarası mevcut"
        return None


class DuplicateCheckService:
    @staticmethod
    def transaction_exists(session, transaction_model, row): return bool(row.get("invoice_number") and session.query(transaction_model).filter(transaction_model.invoice_number == row["invoice_number"], transaction_model.party_name == row.get("party_name")).first())


class RowValidationService:
    @staticmethod
    def validate(session, dataset_type, row):
        errors, warnings, matched_record = [], [], None
        for field in REQUIRED_FIELDS.get(dataset_type, set()):
            if row.get(field) in (None, ""): errors.append(f"{TARGET_FIELDS[field]} eksik")
        if dataset_type == "Gelir-Gider" and not any(row.get(field) is not None for field in ("grand_total", "income", "expense")):
            errors.append("Genel Toplam, Gelir veya Gider alanlarından biri gerekli")
        if dataset_type == "Banka Hareketleri" and not any(row.get(field) is not None for field in ("grand_total", "debit", "credit")):
            errors.append("Genel Toplam, Borç veya Alacak alanlarından biri gerekli")
        if dataset_type == "Restoran Mutabakatı" and not (row.get("supplier_name") or row.get("restaurant_name")):
            errors.append("Tedarikçi veya Restoran eksik")
        if row.get("booking_number"):
            booking = session.query(Booking).filter(Booking.booking_number == row["booking_number"]).first()
            if booking:
                matched_record = f"Rezervasyon #{booking.id}"
            elif dataset_type in {"Tahsilat", "Voucher"}:
                errors.append("İlgili rezervasyon bulunamadı")
        supplier_label = row.get("supplier_name") or row.get("restaurant_name")
        if supplier_label:
            supplier = session.query(Supplier).filter(func.lower(Supplier.name) == supplier_label.lower()).first()
            if supplier:
                matched_record = f"Tedarikçi #{supplier.id}"
        if row.get("currency") is None and "currency" in row: errors.append("Para birimi geçersiz")
        for field in AMOUNT_FIELDS:
            if field in row and row[field] is None: errors.append(f"{TARGET_FIELDS[field]} geçersiz")
        if row.get("paid_amount") is not None and row.get("grand_total") is not None and row["paid_amount"] > row["grand_total"]: errors.append("Ödenen tutar toplamdan büyük")
        if row.get("passenger_count") is not None and row["passenger_count"] < 0: errors.append("Yolcu sayısı geçersiz")
        if dataset_type == "Fatura" and row.get("transaction_date") and row["transaction_date"].date() > datetime.now().date(): warnings.append("Fatura tarihi gelecekte")
        if row.get("subtotal") is not None and row.get("tax_total") is not None and row.get("grand_total") is not None and abs(row["subtotal"] + row["tax_total"] - row["grand_total"]) > Decimal("1.00"): warnings.append("Ara toplam + KDV genel toplamla uyuşmuyor")
        duplicate = DuplicateDetectionService.check(session, dataset_type, row)
        status = "Hatalı" if errors else ("Mükerrer" if duplicate else ("Uyarılı" if warnings else "Hazır"))
        return {"status": status, "messages": errors + warnings + ([duplicate] if duplicate else []), "duplicate": duplicate, "matched_record": matched_record}


class ImportAuditService:
    @staticmethod
    def log(session, event, batch_id, details): session.add(AuditLog(event_type=event, entity_type="import_batch", entity_id=batch_id, details_json=json.dumps(details, ensure_ascii=False, default=str)))


class ImportExecutionService:
    @classmethod
    def execute(cls, session, filename, file_bytes, dataset_type, validated_rows, include_duplicates=False):
        batch = ImportBatch(filename=filename, file_hash=hashlib.sha256(file_bytes).hexdigest(), dataset_type=dataset_type, total_rows=len(validated_rows)); session.add(batch); session.flush()
        result = {"imported": 0, "skipped": 0, "errors": 0, "duplicates": 0, "updated": 0, "customers": 0, "suppliers": 0, "bookings": 0, "transactions": 0}
        try:
            for item in validated_rows:
                row, status = item["row"], item["validation"]["status"]
                if status == "Hatalı": result["errors"] += 1; result["skipped"] += 1; continue
                if status == "Mükerrer" and not include_duplicates: result["duplicates"] += 1; result["skipped"] += 1; continue
                cls._insert(session, batch.id, dataset_type, row, result); result["imported"] += 1
            batch.imported_rows=result["imported"]; batch.skipped_rows=result["skipped"]; batch.error_rows=result["errors"]; batch.duplicate_rows=result["duplicates"]; batch.result_json=json.dumps(result)
            ImportAuditService.log(session, "import_completed", batch.id, result); session.commit()
            from services.analytics_service import clear_analytics_cache
            clear_analytics_cache()
            return batch.id, result
        except Exception:
            session.rollback(); raise

    @staticmethod
    def _insert(session, batch_id, kind, row, result):
        if kind in {"Gelir-Gider", "Fatura"}:
            total = row.get("grand_total") or (row.get("income") or Decimal(0)) - (row.get("expense") or Decimal(0))
            session.add(Transaction(transaction_type=row.get("transaction_type") or ("income" if total >= 0 else "expense"), invoice_type="sale" if total >= 0 else "purchase", transaction_date=row.get("transaction_date") or datetime.utcnow(), due_date=row.get("due_date"), invoice_number=row.get("invoice_number") or row.get("document_number"), description=row.get("description") or row.get("notes"), party_name=row.get("customer_name") or row.get("supplier_name"), currency=row.get("currency") or "TRY", exchange_rate=row.get("exchange_rate") or 1, subtotal=row.get("subtotal") or total - (row.get("tax_total") or 0), tax_total=row.get("tax_total") or 0, grand_total=total, paid_amount=row.get("paid_amount") or row.get("collected_amount") or 0, remaining_amount=row.get("remaining_amount") if row.get("remaining_amount") is not None else total - (row.get("paid_amount") or 0), payment_status=row.get("payment_status") or "Ödenmedi")); result["transactions"] += 1
        elif kind == "Rezervasyon":
            customer = session.query(Customer).filter(func.lower(Customer.first_name) == (row.get("customer_name") or "").lower()).first()
            if not customer: customer=Customer(first_name=row.get("customer_name"), email=row.get("email"), phone=row.get("phone")); session.add(customer); session.flush(); result["customers"] += 1
            tour=session.query(Tour).filter((Tour.code == row.get("tour_code")) | (Tour.name == row.get("tour_name"))).first() if row.get("tour_code") or row.get("tour_name") else None
            session.add(Booking(booking_number=row["booking_number"], booking_date=row.get("transaction_date") or datetime.utcnow(), service_start_date=row.get("service_date"), tour_id=tour.id if tour else None, customer_id=customer.id, passenger_count=row.get("passenger_count") or 0, adult_count=row.get("adult_count") or 0, child_count=row.get("child_count") or 0, currency=row.get("currency") or "TRY", unit_price=row.get("unit_price") or 0, grand_total=row.get("grand_total") or 0, collected_total=row.get("collected_amount") or 0, remaining_amount=row.get("remaining_amount") or 0, booking_status=row.get("payment_status"), voucher_number=row.get("voucher_number"), notes=row.get("notes"))); result["bookings"] += 1
        elif kind == "Tahsilat":
            booking=session.query(Booking).filter(Booking.booking_number == row["booking_number"]).one(); session.add(Collection(booking_id=booking.id, customer_id=booking.customer_id, collection_date=row.get("transaction_date") or datetime.utcnow(), amount=row.get("collected_amount"), amount_in_tl=(row.get("collected_amount") or 0)*(row.get("exchange_rate") or 1), currency=row.get("currency") or "TRY", payment_method=row.get("payment_method"), notes=row.get("notes")))
        elif kind == "Tedarikçi Ödemesi":
            supplier=session.query(Supplier).filter(func.lower(Supplier.name)==row["supplier_name"].lower()).first()
            if not supplier: supplier=Supplier(name=row["supplier_name"], currency=row.get("currency") or "TRY"); session.add(supplier); session.flush(); result["suppliers"] += 1
            session.add(SupplierPayment(supplier_id=supplier.id, invoice_reference=row.get("invoice_number"), service_date=row.get("service_date"), due_date=row.get("due_date"), total_debt=row.get("grand_total") or 0, paid_amount=row.get("paid_amount") or 0, remaining_amount=row.get("remaining_amount") or 0, currency=row.get("currency") or "TRY", payment_status=row.get("payment_status")))
        elif kind == "Tur": session.add(Tour(code=row["tour_code"], name=row["tour_name"], start_location=row.get("start_location"), end_location=row.get("end_location"), departure_datetime=row.get("service_date"), capacity=row.get("capacity") or 0, adult_price=row.get("unit_price") or 0, currency=row.get("currency") or "TRY"))
        elif kind == "Müşteri": session.add(Customer(first_name=row["customer_name"], email=row.get("email"), phone=row.get("phone"), tax_number=row.get("tax_number"))); result["customers"] += 1
        elif kind == "Tedarikçi": session.add(Supplier(name=row["supplier_name"], email=row.get("email"), phone=row.get("phone"), tax_number=row.get("tax_number"), currency=row.get("currency") or "TRY")); result["suppliers"] += 1
        elif kind == "Voucher":
            booking=session.query(Booking).filter(Booking.booking_number==row["booking_number"]).one(); session.add(Voucher(booking_id=booking.id, voucher_number=row["voucher_number"], travel_date=row.get("service_date"), service_name=row.get("tour_name"), notes=row.get("notes")))
        elif kind == "Banka Hareketleri": session.add(BankTransaction(transaction_date=row.get("transaction_date"), description=row.get("description"), reference_number=row.get("document_number"), amount=row.get("grand_total") or row.get("credit") or -(row.get("debit") or 0), currency=row.get("currency") or "TRY", transaction_type=row.get("transaction_type"), import_batch_id=batch_id))
        elif kind == "Restoran Mutabakatı":
            supplier=session.query(Supplier).filter(func.lower(Supplier.name)==(row.get("supplier_name") or row.get("restaurant_name") or "").lower()).first()
            if not supplier: supplier=Supplier(name=row.get("supplier_name") or row.get("restaurant_name"), supplier_type="Restoran"); session.add(supplier); session.flush(); result["suppliers"] += 1
            session.add(SupplierPayment(supplier_id=supplier.id, invoice_reference=row.get("invoice_number") or row.get("voucher_number"), service_date=row.get("service_date"), total_debt=row.get("grand_total") or 0, remaining_amount=row.get("grand_total") or 0, currency=row.get("currency") or "TRY"))
        else: raise ValueError(f"{kind} veri türü için hedef tablo seçilmedi.")


def parse_decimal(value): return ValueNormalizationService.decimal(value) or Decimal("0.00")
def parse_date(value): return ValueNormalizationService.date(value)
def normalize_row(row): return row
def normalize_dataframe(df): return df.to_dict("records") if df is not None else []
