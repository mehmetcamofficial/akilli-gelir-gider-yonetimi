import math
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from database.db import engine
from database.models import (
    Booking, Collection, Customer, Document, DocumentReconciliation, GuideAssignment,
    HotelBooking, ReconciliationDifference, SalesChannel, Staff, Supplier, SupplierPayment,
    Tour, TourCostItem, Transaction,
)


@dataclass
class AnalyticsFilters:
    start_date: date
    end_date: date
    period: str = "Ay"
    tour_id: int | None = None
    tour_type: str | None = None
    sales_channel_id: int | None = None
    sales_person_id: int | None = None
    country: str | None = None
    supplier_id: int | None = None
    hotel_id: int | None = None
    restaurant_id: int | None = None
    guide_id: int | None = None
    currency: str | None = None
    booking_status: str | None = None
    payment_status: str | None = None


def _float(value):
    return float(value or 0)


def _normalized(value):
    text = str(value or "").lower().translate(str.maketrans("çğıöşü", "cgiosu"))
    return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))


def _frame(rows, columns):
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


class AnalyticsQueryService:
    @staticmethod
    def previous_period(filters):
        days = max((filters.end_date - filters.start_date).days + 1, 1)
        previous_end = filters.start_date - timedelta(days=1)
        return AnalyticsFilters(**{**asdict(filters), "start_date": previous_end - timedelta(days=days - 1), "end_date": previous_end})

    @staticmethod
    def booking_query(session, filters):
        query = session.query(Booking).filter(func.date(Booking.booking_date) >= filters.start_date, func.date(Booking.booking_date) <= filters.end_date)
        if filters.tour_id: query = query.filter(Booking.tour_id == filters.tour_id)
        if filters.tour_type: query = query.join(Tour, Booking.tour_id == Tour.id).filter(Tour.tour_type == filters.tour_type)
        if filters.sales_channel_id: query = query.filter(Booking.sales_channel_id == filters.sales_channel_id)
        if filters.sales_person_id: query = query.filter(Booking.sales_person_id == filters.sales_person_id)
        if filters.country: query = query.join(Customer, Booking.customer_id == Customer.id).filter(Customer.nationality == filters.country)
        if filters.currency: query = query.filter(Booking.currency == filters.currency)
        if filters.booking_status: query = query.filter(Booking.booking_status == filters.booking_status)
        if filters.hotel_id: query = query.filter(Booking.id.in_(session.query(HotelBooking.booking_id).filter(HotelBooking.hotel_id == filters.hotel_id)))
        if filters.guide_id: query = query.filter(Booking.id.in_(session.query(GuideAssignment.booking_id).filter(GuideAssignment.guide_id == filters.guide_id)))
        return query

    @staticmethod
    def transaction_query(session, filters):
        query = session.query(Transaction).filter(func.date(Transaction.transaction_date) >= filters.start_date, func.date(Transaction.transaction_date) <= filters.end_date, Transaction.is_deleted.is_(False))
        if filters.currency: query = query.filter(Transaction.currency == filters.currency)
        if filters.payment_status: query = query.filter(Transaction.payment_status == filters.payment_status)
        return query

    @staticmethod
    def supplier_payment_query(session, filters):
        query = session.query(SupplierPayment).filter(func.date(func.coalesce(SupplierPayment.service_date, SupplierPayment.due_date, SupplierPayment.payment_date)) >= filters.start_date, func.date(func.coalesce(SupplierPayment.service_date, SupplierPayment.due_date, SupplierPayment.payment_date)) <= filters.end_date)
        effective_supplier = filters.restaurant_id or filters.supplier_id
        if effective_supplier: query = query.filter(SupplierPayment.supplier_id == effective_supplier)
        if filters.currency: query = query.filter(SupplierPayment.currency == filters.currency)
        if filters.payment_status: query = query.filter(SupplierPayment.payment_status == filters.payment_status)
        return query

    @classmethod
    def snapshot(cls, session, filters):
        bookings = cls.booking_query(session, filters).all()
        transactions = cls.transaction_query(session, filters).all()
        collections = session.query(Collection).filter(func.date(Collection.collection_date) >= filters.start_date, func.date(Collection.collection_date) <= filters.end_date).all()
        payments = cls.supplier_payment_query(session, filters).all()
        reconciliations = session.query(DocumentReconciliation).filter(func.date(DocumentReconciliation.created_at) >= filters.start_date, func.date(DocumentReconciliation.created_at) <= filters.end_date).all()
        return {"bookings": bookings, "transactions": transactions, "collections": collections, "payments": payments, "reconciliations": reconciliations}


class FinancialAnalyticsService:
    @staticmethod
    def metrics(snapshot):
        bookings, transactions = snapshot["bookings"], snapshot["transactions"]
        sales = sum((_float(row.grand_total) for row in bookings), 0.0) + sum((_float(row.grand_total) for row in transactions if row.transaction_type == "income"), 0.0)
        collections = sum((_float(row.amount_in_tl) for row in snapshot["collections"]), 0.0)
        transaction_expense = sum((_float(row.grand_total) for row in transactions if row.transaction_type == "expense"), 0.0)
        supplier_cost = sum((_float(row.total_debt) for row in snapshot["payments"]), 0.0)
        expense = transaction_expense + supplier_cost
        net_profit = sales - expense
        pending = sum((_float(row.remaining_amount) for row in bookings), 0.0)
        supplier_debt = sum((_float(row.remaining_amount) for row in snapshot["payments"]), 0.0)
        booking_count = len(bookings)
        passengers = sum((row.passenger_count or 0 for row in bookings), 0)
        cancelled = sum("iptal" in _normalized(row.booking_status) for row in bookings)
        capacities = {row.tour_id: row.tour.capacity for row in bookings if row.tour_id and row.tour}
        capacity = sum((value or 0 for value in capacities.values()), 0)
        recs = snapshot["reconciliations"]
        mismatches = sum(row.status != "Tam Eşleşti" for row in recs)
        return {
            "total_sales": sales, "total_collections": collections, "total_expense": expense,
            "net_profit": net_profit, "gross_margin": ((sales - supplier_cost) / sales * 100) if sales else None,
            "net_margin": (net_profit / sales * 100) if sales else None,
            "avg_booking": sales / booking_count if booking_count else None, "booking_count": booking_count,
            "passenger_count": passengers, "revenue_per_passenger": sales / passengers if passengers else None,
            "pending_collection": pending, "supplier_debt": supplier_debt,
            "cancellation_rate": cancelled / booking_count * 100 if booking_count else None,
            "occupancy_rate": passengers / capacity * 100 if capacity else None,
            "reconciliation_mismatch_rate": mismatches / len(recs) * 100 if recs else None,
            "collection_rate": collections / sales * 100 if sales else None,
        }

    @staticmethod
    def monthly(snapshot):
        rows = []
        for booking in snapshot["bookings"]:
            rows.append({"Ay": pd.Timestamp(booking.booking_date).to_period("M").to_timestamp(), "Gelir": _float(booking.grand_total), "Gider": 0.0})
        for txn in snapshot["transactions"]:
            rows.append({"Ay": pd.Timestamp(txn.transaction_date).to_period("M").to_timestamp(), "Gelir": _float(txn.grand_total) if txn.transaction_type == "income" else 0.0, "Gider": _float(txn.grand_total) if txn.transaction_type == "expense" else 0.0})
        for payment in snapshot["payments"]:
            stamp = payment.service_date or payment.due_date or payment.payment_date
            if stamp: rows.append({"Ay": pd.Timestamp(stamp).to_period("M").to_timestamp(), "Gelir": 0.0, "Gider": _float(payment.total_debt)})
        if not rows: return pd.DataFrame(columns=["Ay", "Gelir", "Gider", "Net Kâr"])
        frame = pd.DataFrame(rows).groupby("Ay", as_index=False)[["Gelir", "Gider"]].sum()
        frame["Net Kâr"] = frame["Gelir"] - frame["Gider"]
        return frame


@st.cache_data(ttl=300, show_spinner=False)
def cached_financial_analytics(filter_values, cache_token):
    """Short-lived aggregate cache; cache_token and write hooks control invalidation."""
    filters = AnalyticsFilters(**filter_values)
    session = sessionmaker(bind=engine)()
    session.info["skip_analytics_cache_clear"] = True
    try:
        current = AnalyticsQueryService.snapshot(session, filters)
        previous = AnalyticsQueryService.snapshot(session, AnalyticsQueryService.previous_period(filters))
        return FinancialAnalyticsService.metrics(current), FinancialAnalyticsService.metrics(previous), FinancialAnalyticsService.monthly(current)
    finally:
        session.close()


class TourAnalyticsService:
    @staticmethod
    def profitability(session, filters):
        bookings = AnalyticsQueryService.booking_query(session, filters).all()
        tours = {row.tour_id: row.tour for row in bookings if row.tour_id and row.tour}
        general_expense = sum(_float(row.grand_total) for row in AnalyticsQueryService.transaction_query(session, filters).filter(Transaction.transaction_type == "expense").all())
        allocation = general_expense / len(tours) if tours else 0
        rows = []
        for tour_id, tour in tours.items():
            related = [row for row in bookings if row.tour_id == tour_id]
            revenue = sum(_float(row.grand_total) for row in related)
            passengers = sum(row.passenger_count or 0 for row in related)
            direct = sum(_float(row.amount) for row in session.query(TourCostItem).filter(TourCostItem.tour_id == tour_id).all())
            direct += sum(_float(row.total_debt) for row in AnalyticsQueryService.supplier_payment_query(session, filters).filter(SupplierPayment.tour_id == tour_id).all())
            gross, net = revenue - direct, revenue - direct - allocation
            capacity = (tour.capacity or 0) * max(len(related), 1)
            variable = direct / passengers if passengers else 0
            sale_price = revenue / passengers if passengers else _float(tour.adult_price)
            contribution = sale_price - variable
            fixed = allocation
            break_even = math.ceil(fixed / contribution) if contribution > 0 else None
            rows.append({
                "Tur ID": tour_id, "Tur": tour.name, "Tur Türü": tour.tour_type, "Toplam Gelir": revenue,
                "Doğrudan Maliyet": direct, "Dağıtılan Genel Gider": allocation, "Brüt Kâr": gross, "Net Kâr": net,
                "Kâr Marjı %": net / revenue * 100 if revenue else None, "Yolcu": passengers,
                "Doluluk %": passengers / capacity * 100 if capacity else None,
                "Yolcu Başına Gelir": revenue / passengers if passengers else None,
                "Yolcu Başına Maliyet": (direct + allocation) / passengers if passengers else None,
                "Yolcu Başına Kâr": net / passengers if passengers else None,
                "Tedarikçi Maliyet Payı %": direct / revenue * 100 if revenue else None,
                "Başa Baş Yolcu": break_even, "Eksik Yolcu": max((break_even or 0) - passengers, 0),
                "Tam Kapasite Tahmini Kâr": sale_price * capacity - variable * capacity - fixed if capacity else None,
            })
        return pd.DataFrame(rows)


class ReservationAnalyticsService:
    @staticmethod
    def summary(bookings):
        count = len(bookings); cancelled = sum("iptal" in _normalized(row.booking_status) for row in bookings)
        confirmed = sum(any(word in _normalized(row.booking_status) for word in ("kesin", "onay")) for row in bookings)
        values = [_float(row.grand_total) for row in bookings]
        passengers = [row.passenger_count or 0 for row in bookings]
        leads = [(row.service_start_date.date() - row.booking_date.date()).days for row in bookings if row.service_start_date and row.booking_date]
        return {"count": count, "confirmed_rate": confirmed / count * 100 if count else None, "cancellation_rate": cancelled / count * 100 if count else None, "average_value": sum(values) / count if count else None, "average_passengers": sum(passengers) / count if count else None, "average_lead_days": sum(leads) / len(leads) if leads else None}


class SupplierAnalyticsService:
    @staticmethod
    def performance(session, filters):
        payments = AnalyticsQueryService.supplier_payment_query(session, filters).all()
        grouped = {}
        for payment in payments:
            supplier = getattr(payment, "supplier", None) or session.get(Supplier, payment.supplier_id)
            item = grouped.setdefault(payment.supplier_id, {"Tedarikçi ID": payment.supplier_id, "Tedarikçi": supplier.name if supplier else f"#{payment.supplier_id}", "Fatura Toplamı": 0.0, "Ödenen": 0.0, "Bakiye": 0.0, "Fatura Sayısı": 0, "Gecikme Günleri": []})
            item["Fatura Toplamı"] += _float(payment.total_debt); item["Ödenen"] += _float(payment.paid_amount); item["Bakiye"] += _float(payment.remaining_amount); item["Fatura Sayısı"] += 1
            if payment.due_date and payment.payment_date: item["Gecikme Günleri"].append(max((payment.payment_date.date() - payment.due_date.date()).days, 0))
        differences = session.query(DocumentReconciliation).filter(func.date(DocumentReconciliation.created_at) >= filters.start_date, func.date(DocumentReconciliation.created_at) <= filters.end_date, DocumentReconciliation.matched_entity_type == "supplier").all()
        mismatch_counts = {}
        for row in differences:
            if row.status != "Tam Eşleşti": mismatch_counts[row.matched_entity_id] = mismatch_counts.get(row.matched_entity_id, 0) + 1
        rows = []
        total_spend = sum(item["Fatura Toplamı"] for item in grouped.values())
        for supplier_id, item in grouped.items():
            mismatch = mismatch_counts.get(supplier_id, 0); invoice_count = item["Fatura Sayısı"]
            rate = mismatch / invoice_count * 100 if invoice_count else 0
            delay = sum(item["Gecikme Günleri"]) / len(item["Gecikme Günleri"]) if item["Gecikme Günleri"] else 0
            score = min(100, rate * .6 + min(delay, 60) * .5 + (20 if item["Bakiye"] > item["Fatura Toplamı"] * .5 else 0))
            risk = "Yüksek Risk" if score >= 60 else ("Orta Risk" if score >= 30 else "Düşük Risk")
            reason = f"Uyuşmazlık oranı %{rate:.1f}, ortalama ödeme gecikmesi {delay:.1f} gün."
            rows.append({**{key: value for key, value in item.items() if key != "Gecikme Günleri"}, "Ortalama Gecikme": delay, "Uyuşmazlık Sayısı": mismatch, "Uyuşmazlık %": rate, "Toplam Maliyet Payı %": item["Fatura Toplamı"] / total_spend * 100 if total_spend else 0, "Risk Puanı": score, "Risk": risk, "Risk Açıklaması": reason})
        return pd.DataFrame(rows)


class ReconciliationAnalyticsService:
    @staticmethod
    def summary(session, filters):
        records = session.query(DocumentReconciliation).filter(func.date(DocumentReconciliation.created_at) >= filters.start_date, func.date(DocumentReconciliation.created_at) <= filters.end_date).all()
        statuses = pd.Series([row.status for row in records], dtype="object").value_counts()
        discrepancy = sum(abs(_float(row.difference_amount)) for row in records)
        prevented = sum(max(_float(row.difference_amount), 0) for row in records if row.status in {"Kritik Uyumsuzluk", "İnceleme Gerekli"})
        confidence = []
        for row in records:
            try:
                extracted = __import__("json").loads(row.extracted_json); incoming = extracted.get("incoming", extracted); confidence.append(float(incoming.get("confidence") or 0))
            except Exception: pass
        metrics = {"documents": len(records), "exact": int(statuses.get("Tam Eşleşti", 0)), "small": int(statuses.get("Küçük Fark Var", 0)), "review": int(statuses.get("İnceleme Gerekli", 0)), "critical": int(statuses.get("Kritik Uyumsuzluk", 0)), "unmatched": int(statuses.get("Eşleşen Kayıt Bulunamadı", 0) + statuses.get("Eşleşen Acenta Kaydı Bulunamadı", 0)), "discrepancy": discrepancy, "prevented_overpayment": prevented, "average_ai_confidence": sum(confidence) / len(confidence) * 100 if confidence else None}
        status_frame = statuses.rename_axis("Durum").reset_index(name="Belge Sayısı")
        differences = session.query(ReconciliationDifference.field_name, func.count(ReconciliationDifference.id)).join(DocumentReconciliation, ReconciliationDifference.reconciliation_id == DocumentReconciliation.id).filter(func.date(DocumentReconciliation.created_at) >= filters.start_date, func.date(DocumentReconciliation.created_at) <= filters.end_date).group_by(ReconciliationDifference.field_name).all()
        return metrics, status_frame, _frame(differences, ["Sorun Alanı", "Sayı"])


class StatisticalSummaryService:
    @staticmethod
    def describe(values, label="Değer"):
        series = pd.Series([float(value) for value in values if value is not None], dtype="float64")
        if series.empty: return {"count": 0, "message": "Yeterli veri yok"}
        result = {"count": int(series.count()), "mean": series.mean(), "median": series.median(), "min": series.min(), "max": series.max(), "std": series.std() if len(series) > 1 else None, "q1": series.quantile(.25), "q3": series.quantile(.75)}
        result["message"] = f"{label} kayıtlarının yarısı {result['median']:,.2f} değerinin altındadır. Tipik aralık {result['q1']:,.2f}–{result['q3']:,.2f}."
        return result


class AnomalyDetectionService:
    @staticmethod
    def iqr(values, records=None, label="Tutar"):
        series = pd.Series([float(value) for value in values if value is not None], dtype="float64")
        if len(series) < 4: return []
        q1, q3 = series.quantile(.25), series.quantile(.75); iqr = q3 - q1; low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        return [{"Değer": value, "Normal Aralık": f"{low:,.2f}–{high:,.2f}", "Neden": f"{label} normal aralığın dışında", "Önem": "Yüksek" if value > high * 1.5 else "Orta", "İlgili Kayıt": (records[index] if records and index < len(records) else index + 1), "Öneri": "Kaynak belge ve sözleşme fiyatını kontrol edin."} for index, value in enumerate(series) if value < low or value > high]


class ForecastingService:
    @staticmethod
    def next_30_days(session, today=None):
        today = today or date.today(); end = today + timedelta(days=30)
        confirmed_collections = session.query(func.coalesce(func.sum(Collection.amount_in_tl), 0)).filter(func.date(Collection.collection_date) >= today, func.date(Collection.collection_date) <= end).scalar() or 0
        expected_collections = session.query(func.coalesce(func.sum(Booking.remaining_amount), 0)).filter(func.date(Booking.final_payment_date) >= today, func.date(Booking.final_payment_date) <= end).scalar() or 0
        confirmed_payments = session.query(func.coalesce(func.sum(SupplierPayment.remaining_amount), 0)).filter(func.date(SupplierPayment.due_date) >= today, func.date(SupplierPayment.due_date) <= end).scalar() or 0
        return {"confirmed_collections": _float(confirmed_collections), "expected_collections": _float(expected_collections), "confirmed_payments": _float(confirmed_payments), "net_position": _float(confirmed_collections) + _float(expected_collections) - _float(confirmed_payments), "method": "Kesin tahsilatlar, açık rezervasyon vadeleri ve tedarikçi ödeme vadeleri kullanıldı.", "confidence": "Orta"}


class ManagementInsightService:
    @staticmethod
    def build(current, previous, supplier_frame, reconciliation):
        insights = []
        for key, label in (("net_profit", "Net kâr"), ("total_expense", "Toplam gider"), ("collection_rate", "Tahsilat gerçekleşme oranı")):
            now, before = current.get(key), previous.get(key)
            if now is None or before in (None, 0): insights.append(f"{label} değişimini yorumlamak için yeterli önceki dönem verisi yok.")
            else:
                change = (now - before) / abs(before) * 100
                insights.append(f"{label} önceki döneme göre %{abs(change):.1f} {'arttı' if change >= 0 else 'azaldı'}.")
        if reconciliation.get("prevented_overpayment", 0) > 0: insights.append(f"Belge mutabakatı bu dönemde {reconciliation['prevented_overpayment']:,.2f} tutarında olası fazla ödeme riski gösterdi.")
        if not supplier_frame.empty:
            risky = supplier_frame[supplier_frame["Risk"] == "Yüksek Risk"]
            if not risky.empty: insights.append(f"{len(risky)} tedarikçi yüksek risk düzeyinde; uyuşmazlık ve ödeme gecikmeleri incelenmeli.")
        return insights


class AnalyticsExportService:
    @staticmethod
    def excel(tables):
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            for name, frame in tables.items(): frame.to_excel(writer, sheet_name=name[:31], index=False)
        return output.getvalue()

    @staticmethod
    def csv(frame): return frame.to_csv(index=False).encode("utf-8-sig")

    @staticmethod
    def executive_pdf(title, filters, metrics, insights):
        def safe(value):
            return str(value).translate(str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")).encode("latin-1", "replace").decode("latin-1")
        output = BytesIO(); pdf = canvas.Canvas(output, pagesize=A4); width, height = A4
        pdf.setFont("Helvetica-Bold", 16); pdf.drawString(40, height - 45, safe(title))
        pdf.setFont("Helvetica", 9); pdf.drawString(40, height - 65, f"Dönem: {filters.start_date} - {filters.end_date}")
        y = height - 95
        for key, value in metrics.items():
            pdf.drawString(40, y, safe(f"{key}: {value if value is not None else 'Yeterli veri yok'}")); y -= 16
            if y < 80: break
        y -= 8; pdf.setFont("Helvetica-Bold", 11); pdf.drawString(40, y, "Yönetim İçgörüleri"); y -= 18; pdf.setFont("Helvetica", 8)
        for insight in insights[:6]:
            safe_insight = safe(insight)
            pdf.drawString(45, y, f"- {safe_insight[:105]}"); y -= 14
        pdf.save(); return output.getvalue()


def clear_analytics_cache():
    try:
        import streamlit as st
        st.cache_data.clear()
    except Exception:
        pass
