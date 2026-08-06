from datetime import date
from types import SimpleNamespace

import pandas as pd

from services.analytics_service import (
    AnalyticsExportService, AnalyticsFilters, AnalyticsQueryService,
    AnomalyDetectionService, FinancialAnalyticsService,
    ManagementInsightService, StatisticalSummaryService,
)


def _booking(total=1000, passengers=2, remaining=200, status="Kesinleşti"):
    return SimpleNamespace(
        grand_total=total, passenger_count=passengers, remaining_amount=remaining,
        booking_status=status, tour_id=None, tour=None,
    )


def _snapshot():
    return {
        "bookings": [_booking(), _booking(500, 1, 0, "İptal")],
        "transactions": [SimpleNamespace(grand_total=200, transaction_type="expense")],
        "collections": [SimpleNamespace(amount_in_tl=900)],
        "payments": [SimpleNamespace(total_debt=300, remaining_amount=100)],
        "reconciliations": [SimpleNamespace(status="Kritik Uyumsuzluk")],
    }


def test_financial_metrics_are_calculated_from_records():
    metrics = FinancialAnalyticsService.metrics(_snapshot())
    assert metrics["total_sales"] == 1500
    assert metrics["total_collections"] == 900
    assert metrics["total_expense"] == 500
    assert metrics["net_profit"] == 1000
    assert metrics["passenger_count"] == 3
    assert metrics["cancellation_rate"] == 50
    assert metrics["collection_rate"] == 60


def test_previous_period_has_same_number_of_days():
    current = AnalyticsFilters(date(2026, 8, 1), date(2026, 8, 31))
    previous = AnalyticsQueryService.previous_period(current)
    assert previous.start_date == date(2026, 7, 1)
    assert previous.end_date == date(2026, 7, 31)


def test_statistical_summary_is_accountant_friendly():
    result = StatisticalSummaryService.describe([100, 200, 300, 400], "Rezervasyon tutarı")
    assert result["median"] == 250
    assert result["q1"] == 175
    assert "yarısı" in result["message"]
    assert StatisticalSummaryService.describe([], "Tutar")["message"] == "Yeterli veri yok"


def test_iqr_anomaly_detection_requires_enough_data_and_explains_result():
    assert AnomalyDetectionService.iqr([1, 2, 3]) == []
    anomalies = AnomalyDetectionService.iqr([10, 10, 11, 11, 12, 100], label="Fatura")
    assert anomalies
    assert anomalies[0]["Normal Aralık"]
    assert anomalies[0]["Öneri"]


def test_management_insights_do_not_divide_by_zero():
    insights = ManagementInsightService.build(
        {"net_profit": 100, "total_expense": 50, "collection_rate": 80},
        {"net_profit": 0, "total_expense": 0, "collection_rate": None},
        pd.DataFrame(), {"prevented_overpayment": 0},
    )
    assert all("yeterli" in item.casefold() for item in insights)


def test_excel_csv_and_pdf_exports_are_real_files():
    frame = pd.DataFrame([{"Ay": "2026-08", "Gelir": 1000}])
    excel = AnalyticsExportService.excel({"Finans": frame})
    csv = AnalyticsExportService.csv(frame)
    pdf = AnalyticsExportService.executive_pdf("Yonetim", AnalyticsFilters(date(2026, 8, 1), date(2026, 8, 31)), {"Toplam Satış": "1.000 TL"}, ["Net kâr arttı."])
    assert excel.startswith(b"PK")
    assert csv.startswith(b"\xef\xbb\xbf")
    assert pdf.startswith(b"%PDF")
