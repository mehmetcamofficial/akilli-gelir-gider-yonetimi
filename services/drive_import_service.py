from datetime import datetime
from decimal import Decimal
import pandas as pd

COLUMN_MAP = {
    "fatura no": "invoice_number",
    "fatura numarası": "invoice_number",
    "belge no": "invoice_number",
    "tarih": "transaction_date",
    "belge tarihi": "transaction_date",
    "vade tarihi": "due_date",
    "ödeme tarihi": "due_date",
    "firma": "party_name",
    "müşteri": "party_name",
    "taraf": "party_name",
    "tutar": "grand_total",
    "genel toplam": "grand_total",
    "toplam": "grand_total",
    "kdv": "tax_total",
    "vergiler": "tax_total",
    "açıklama": "description",
    "not": "description",
    "işlem türü": "transaction_type",
    "tür": "transaction_type",
    "tahsilat durumu": "payment_status",
    "ödeme durumu": "payment_status",
    "rezervasyon no": "booking_number",
    "bk no": "booking_number",
    "hesap": "account_name",
}

TRANSACTION_TYPE_MAP = {
    "gelir": "income",
    "gider": "expense",
    "satış": "income",
    "alis": "expense",
    "alım": "expense",
    "purchase": "expense",
    "expense": "expense",
    "income": "income",
    "sale": "income",
    "fatura": "income",
}

PAYMENT_STATUS_MAP = {
    "ödenmedi": "Ödenmedi",
    "ödendi": "Ödendi",
    "kısmen ödendi": "Kısmen ödendi",
    "beklemede": "Beklemede",
    "iptal": "İptal",
}


def normalize_column_name(name):
    if not isinstance(name, str):
        return None
    return name.strip().lower().replace("_", " ").replace("-", " ")


def parse_decimal(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value)).quantize(Decimal("0.00"))
    except Exception:
        try:
            cleaned = str(value).replace(" ", "").replace(".", "").replace(",", ".")
            return Decimal(cleaned).quantize(Decimal("0.00"))
        except Exception:
            return Decimal("0.00")


def parse_date(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return pd.to_datetime(value)
    except Exception:
        return None


def normalize_row(row):
    normalized = {}
    for source_key, value in row.items():
        dest = COLUMN_MAP.get(normalize_column_name(source_key))
        if not dest:
            continue
        normalized[dest] = value
    return normalized


def normalize_dataframe(df):
    if df is None or df.empty:
        return []

    cleaned = df.copy()
    cleaned.columns = [normalize_column_name(col) or str(col) for col in cleaned.columns]

    records = []
    for _, row in cleaned.iterrows():
        row_data = normalize_row(row.to_dict())
        if not row_data:
            continue

        transaction_type = row_data.get("transaction_type")
        if transaction_type:
            transaction_type = str(transaction_type).strip().lower()
            row_data["transaction_type"] = TRANSACTION_TYPE_MAP.get(transaction_type, "income")

        grand_total = parse_decimal(row_data.get("grand_total"))
        if "transaction_type" not in row_data or not row_data.get("transaction_type"):
            row_data["transaction_type"] = "income" if grand_total >= 0 else "expense"

        row_data["transaction_date"] = parse_date(row_data.get("transaction_date"))
        row_data["due_date"] = parse_date(row_data.get("due_date"))
        row_data["grand_total"] = grand_total
        row_data["tax_total"] = parse_decimal(row_data.get("tax_total"))
        row_data["subtotal"] = parse_decimal(row_data.get("subtotal")) if row_data.get("subtotal") is not None else parse_decimal(grand_total - row_data["tax_total"])
        row_data["payment_status"] = PAYMENT_STATUS_MAP.get(str(row_data.get("payment_status", "")).strip().lower(), row_data.get("payment_status") or "Ödenmedi")
        row_data["party_name"] = str(row_data.get("party_name") or "").strip()
        row_data["description"] = str(row_data.get("description") or "").strip()
        row_data["invoice_number"] = str(row_data.get("invoice_number") or "").strip()
        row_data["booking_number"] = str(row_data.get("booking_number") or "").strip()
        records.append(row_data)

    return records
