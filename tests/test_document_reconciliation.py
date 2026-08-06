import json
import unittest
from decimal import Decimal

from services.document_reconciliation_service import (
    AIExtractionError,
    EXTRACTION_FIELDS,
    OpenRouterDocumentExtractor,
    ReconciliationEngine,
)


def document(**overrides):
    base = {
        "document_type": "supplier_invoice", "supplier_name": "ABC Turizm",
        "invoice_number": "INV-1", "document_date": "2026-08-07",
        "voucher_number": "V-1", "booking_number": "B-1", "tour_name": "Efes",
        "service_date": "2026-08-07", "passenger_count": 2, "adult_count": 2,
        "child_count": 0, "guide_count": 0, "driver_count": 0,
        "free_person_count": 0, "currency": "TRY", "unit_price": 100,
        "subtotal": 200, "tax_amount": 40, "grand_total": 240,
        "paid_amount": 100, "remaining_amount": 140, "payment_method": "Havale",
        "notes": None, "additional_charges": 0, "discounts": 0, "tax_rate": 20,
        "confidence": 0.95,
        "unreadable_fields": [],
    }
    base.update(overrides)
    return base


def agency(**overrides):
    base = document()
    base.pop("document_type"); base.pop("invoice_number"); base.pop("document_date")
    base.pop("tour_name"); base.pop("confidence"); base.pop("unreadable_fields")
    base["booking_status"] = "Kesinleşti"
    base.update(overrides)
    return base


class ReconciliationEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ReconciliationEngine()

    def test_exact_match(self):
        self.assertEqual(self.engine.reconcile(document(), agency())["status"], "Tam Eşleşti")

    def test_passenger_count_mismatch(self):
        result = self.engine.reconcile(document(passenger_count=3), agency())
        self.assertTrue(any(item["field"] == "passenger_count" for item in result["field_differences"]))

    def test_unit_price_mismatch(self):
        result = self.engine.reconcile(document(unit_price=120), agency())
        self.assertTrue(any(item["field"] == "unit_price" for item in result["field_differences"]))

    def test_duplicate_invoice(self):
        self.assertEqual(self.engine.reconcile(document(), agency(), duplicate_invoice=True)["status"], "Kritik Uyumsuzluk")

    def test_voucher_mismatch(self):
        result = self.engine.reconcile(document(voucher_number="OTHER"), agency())
        self.assertTrue(any(item["field"] == "voucher_number" for item in result["field_differences"]))

    def test_currency_mismatch(self):
        result = self.engine.reconcile(document(currency="EUR"), agency())
        self.assertTrue(any(item["field"] == "currency" for item in result["field_differences"]))

    def test_date_mismatch(self):
        result = self.engine.reconcile(document(service_date="2026-08-12"), agency())
        self.assertTrue(any(item["field"] == "service_date" for item in result["field_differences"]))

    def test_total_mismatch(self):
        result = self.engine.reconcile(document(grand_total=300), agency())
        self.assertTrue(any(item["field"] == "grand_total" for item in result["field_differences"]))

    def test_no_internal_record_found(self):
        result = self.engine.reconcile(document(), {})
        self.assertEqual(result["status"], "Eşleşen Kayıt Bulunamadı")

    def test_subtotal_tax_and_total_are_deterministic(self):
        result = self.engine.reconcile(document(subtotal=250, tax_amount=30, grand_total=270), agency())
        fields = {item["field"] for item in result["field_differences"]}
        self.assertIn("subtotal_calculation", fields)
        self.assertIn("tax_calculation", fields)
        self.assertIn("total_calculation", fields)

    def test_rounding_tolerance(self):
        result = ReconciliationEngine(amount_tolerance=Decimal("0.05")).reconcile(document(grand_total=240.02), agency())
        self.assertEqual(result["status"], "Tam Eşleşti")

    def test_low_confidence_extraction(self):
        result = self.engine.reconcile(document(confidence=0.4), agency())
        self.assertTrue(any(item["field"] == "confidence" for item in result["field_differences"]))


class ExtractorFailureTests(unittest.TestCase):
    def test_ai_unavailable_fallback(self):
        with self.assertRaises(AIExtractionError):
            OpenRouterDocumentExtractor(None)

    def test_malformed_ai_json(self):
        extractor = OpenRouterDocumentExtractor("test", transport=lambda payload: {"choices": [{"message": {"content": "not-json"}}]})
        with self.assertRaises(AIExtractionError):
            extractor.extract(b"fake", "receipt.png", "image/png")

    def test_strict_schema_response(self):
        import fitz
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "Invoice INV-1 total 240 TRY")
        file_bytes = pdf.tobytes()
        payload = document()
        extractor = OpenRouterDocumentExtractor("test", transport=lambda request: {"choices": [{"message": {"content": json.dumps(payload)}}]})
        self.assertEqual(set(extractor.extract(file_bytes, "invoice.pdf", "application/pdf")), set(EXTRACTION_FIELDS))


if __name__ == "__main__":
    unittest.main()
