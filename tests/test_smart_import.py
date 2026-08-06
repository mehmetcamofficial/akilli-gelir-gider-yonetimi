from io import BytesIO

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Transaction, Voucher
from services.drive_import_service import (
    ColumnMappingService,
    DatasetTypeClassifier,
    DuplicateDetectionService,
    ExcelFileReader,
    HeaderDetectionService,
    ImportExecutionService,
    RowValidationService,
    ValueNormalizationService,
)


def _xlsx(rows, merged=False):
    output = BytesIO()
    frame = pd.DataFrame(rows)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, header=False)
        if merged:
            writer.book.active.merge_cells("A1:D1")
    return output.getvalue()


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_turkish_english_and_mixed_column_mapping():
    mapping = ColumnMappingService.analyze(["Rezervasyon No", "Customer", "Grand Total", "KDV"])
    assert mapping["Rezervasyon No"]["target"] == "booking_number"
    assert mapping["Customer"]["target"] == "customer_name"
    assert mapping["Grand Total"]["target"] == "grand_total"
    assert mapping["KDV"]["target"] == "tax_total"


def test_title_row_blank_rows_and_merged_cells_are_cleaned():
    content = _xlsx([
        ["2026 Yaz Sezonu", None, None, None],
        [None, None, None, None],
        ["Rezervasyon No", "Müşteri", "Yolcu Sayısı", "Tutar"],
        ["R-1", "Ayşe", 2, "1.250,50 TL"],
        [None, None, None, None],
    ], merged=True)
    df, header = ExcelFileReader.analyze(content, "ornek.xlsx")
    assert header == 2
    assert list(df.columns) == ["Rezervasyon No", "Müşteri", "Yolcu Sayısı", "Tutar"]
    assert len(df) == 1


def test_currency_number_formats_and_malformed_dates():
    assert ValueNormalizationService.decimal("1.234,56 ₺") == ValueNormalizationService.decimal("1234.56")
    assert ValueNormalizationService.decimal("€ 2,500.75") == ValueNormalizationService.decimal("2500.75")
    assert ValueNormalizationService.currency("₺") == "TRY"
    assert ValueNormalizationService.currency("eur") == "EUR"
    assert ValueNormalizationService.date("tarih değil") is None
    assert ValueNormalizationService.date(45292) is not None


def test_duplicate_invoice_and_voucher_detection():
    session = _session()
    try:
        session.add(Transaction(transaction_type="income", invoice_number="INV-1"))
        session.add(Voucher(booking_id=1, voucher_number="V-1"))
        session.commit()
        assert DuplicateDetectionService.check(session, "Fatura", {"invoice_number": "INV-1"})
        assert DuplicateDetectionService.check(session, "Voucher", {"voucher_number": "V-1"})
    finally:
        session.close()


def test_dataset_type_detection_for_requested_examples():
    cases = {
        "Rezervasyon": ["Booking No", "Customer", "Pax"],
        "Restoran Mutabakatı": ["Restaurant", "Voucher No", "Pax"],
        "Gelir-Gider": ["Gelir", "Gider", "Tarih"],
        "Tahsilat": ["Rezervasyon No", "Tahsil Edilen"],
    }
    for expected, columns in cases.items():
        detected, confidence = DatasetTypeClassifier.classify(ColumnMappingService.analyze(columns))
        assert detected == expected
        assert confidence >= 0.34


def test_validation_reports_missing_invalid_and_duplicate_rows():
    session = _session()
    try:
        invalid = RowValidationService.validate(session, "Fatura", {"invoice_number": "", "grand_total": None})
        assert invalid["status"] == "Hatalı"
        assert any("eksik" in message for message in invalid["messages"])
    finally:
        session.close()


def test_valid_income_expense_row_is_imported_transactionally():
    session = _session()
    try:
        row = {
            "transaction_date": ValueNormalizationService.date("07.08.2026"),
            "invoice_number": "INV-NEW",
            "grand_total": ValueNormalizationService.decimal("1.250,50"),
            "tax_total": ValueNormalizationService.decimal("250,10"),
            "currency": "TRY",
        }
        validated = [{"row": row, "validation": RowValidationService.validate(session, "Fatura", row)}]
        batch_id, result = ImportExecutionService.execute(session, "faturalar.xlsx", b"test", "Fatura", validated)
        assert batch_id
        assert result["imported"] == 1
        saved = session.query(Transaction).filter(Transaction.invoice_number == "INV-NEW").one()
        assert saved.grand_total == ValueNormalizationService.decimal("1.250,50")
    finally:
        session.close()
