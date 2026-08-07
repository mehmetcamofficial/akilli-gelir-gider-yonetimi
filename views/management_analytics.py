from dataclasses import asdict
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy.orm import sessionmaker

from database.db import engine
from database.models import Booking, Customer, Guide, Hotel, SalesChannel, Staff, Supplier, Tour, Transaction, CurrentAccount, CurrentAccountMovement, OpenItem, AccountReconciliation
from services.analytics_service import (
    AnalyticsExportService, AnalyticsFilters, AnalyticsQueryService,
    AnomalyDetectionService, FinancialAnalyticsService, ForecastingService,
    ManagementInsightService, ReconciliationAnalyticsService,
    ReservationAnalyticsService, StatisticalSummaryService,
    SupplierAnalyticsService, TourAnalyticsService,
    cached_financial_analytics,
)
from utils.ui import empty_state, format_currency, page_header, section_header


Session = sessionmaker(bind=engine)
KPI_LABELS = {
    "total_sales": "Toplam Satış", "total_collections": "Toplam Tahsilat", "total_expense": "Toplam Gider",
    "net_profit": "Net Kâr", "gross_margin": "Brüt Kâr Marjı", "net_margin": "Net Kâr Marjı",
    "avg_booking": "Ortalama Rezervasyon Tutarı", "booking_count": "Toplam Rezervasyon",
    "passenger_count": "Toplam Yolcu", "revenue_per_passenger": "Ortalama Kişi Başı Gelir",
    "pending_collection": "Bekleyen Tahsilat", "supplier_debt": "Tedarikçi Borcu",
    "cancellation_rate": "İptal Oranı", "occupancy_rate": "Ortalama Doluluk",
    "reconciliation_mismatch_rate": "Belge Uyuşmazlık Oranı", "collection_rate": "Tahsilat Gerçekleşme Oranı",
}
MONEY_KEYS = {"total_sales", "total_collections", "total_expense", "net_profit", "avg_booking", "revenue_per_passenger", "pending_collection", "supplier_debt"}
PERCENT_KEYS = {"gross_margin", "net_margin", "cancellation_rate", "occupancy_rate", "reconciliation_mismatch_rate", "collection_rate"}


def _quick_dates(option):
    today = date.today()
    if option == "Bugün": return today, today
    if option == "Son 7 Gün": return today - timedelta(days=6), today
    if option == "Bu Ay": return today.replace(day=1), today
    if option == "Geçen Ay":
        end = today.replace(day=1) - timedelta(days=1); return end.replace(day=1), end
    if option == "Son 3 Ay": return today - timedelta(days=89), today
    if option == "Bu Yıl": return today.replace(month=1, day=1), today
    if option == "Geçen Yıl": return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return st.session_state.get("analytics_custom_start", today - timedelta(days=29)), st.session_state.get("analytics_custom_end", today)


def _options(session, model, field, condition=None):
    query = session.query(field).distinct().filter(field.isnot(None))
    if condition is not None: query = query.filter(condition)
    return sorted([row[0] for row in query.all() if row[0]])


def _select_record(label, records, formatter, key):
    options = [None] + records
    return st.selectbox(label, options, format_func=lambda value: "Tümü" if value is None else formatter(value), key=key)


def _filters(session):
    with st.container(border=True):
        st.markdown("#### Ortak Filtreler")
        top = st.columns([1.2, 1.5, 1])
        quick = top[0].selectbox("Hızlı tarih", ["Bugün", "Son 7 Gün", "Bu Ay", "Geçen Ay", "Son 3 Ay", "Bu Yıl", "Geçen Yıl", "Özel Tarih"], index=4)
        start, end = _quick_dates(quick)
        if quick == "Özel Tarih":
            selected = top[1].date_input("Tarih aralığı", value=(start, end), key="analytics_custom_range")
            if isinstance(selected, (tuple, list)) and len(selected) == 2: start, end = selected
        else: top[1].date_input("Tarih aralığı", value=(start, end), disabled=True, key=f"analytics_range_{quick}")
        period = top[2].selectbox("Gruplama", ["Gün", "Hafta", "Ay", "Çeyrek", "Yıl"], index=2)
        tours = session.query(Tour).order_by(Tour.name).all(); channels = session.query(SalesChannel).order_by(SalesChannel.name).all(); staff = session.query(Staff).order_by(Staff.first_name).all()
        suppliers = session.query(Supplier).order_by(Supplier.name).all(); restaurants = [row for row in suppliers if "restoran" in (row.supplier_type or "").casefold()]
        hotels = session.query(Hotel).order_by(Hotel.name).all(); guides = session.query(Guide).order_by(Guide.first_name).all()
        rows = st.columns(4)
        with rows[0]: tour = _select_record("Tur", tours, lambda x: x.name, "analytics_tour")
        tour_type = rows[1].selectbox("Tur türü", [None] + _options(session, Tour, Tour.tour_type), format_func=lambda x: x or "Tümü")
        channel = rows[2].selectbox("Satış kanalı", [None] + channels, format_func=lambda x: "Tümü" if x is None else x.name)
        person = rows[3].selectbox("Satış personeli", [None] + staff, format_func=lambda x: "Tümü" if x is None else f"{x.first_name} {x.last_name}")
        rows = st.columns(4)
        country = rows[0].selectbox("Müşteri ülkesi", [None] + _options(session, None, Customer.nationality), format_func=lambda x: x or "Tümü")
        supplier = rows[1].selectbox("Tedarikçi", [None] + suppliers, format_func=lambda x: "Tümü" if x is None else x.name)
        hotel = rows[2].selectbox("Otel", [None] + hotels, format_func=lambda x: "Tümü" if x is None else x.name)
        restaurant = rows[3].selectbox("Restoran", [None] + restaurants, format_func=lambda x: "Tümü" if x is None else x.name)
        rows = st.columns(4)
        guide = rows[0].selectbox("Rehber", [None] + guides, format_func=lambda x: "Tümü" if x is None else f"{x.first_name} {x.last_name}")
        currency = rows[1].selectbox("Para birimi", [None, "TRY", "EUR", "USD", "GBP"], format_func=lambda x: x or "Tümü")
        booking_status = rows[2].selectbox("Rezervasyon durumu", [None] + _options(session, None, Booking.booking_status), format_func=lambda x: x or "Tümü")
        payment_status = rows[3].selectbox("Ödeme durumu", [None] + _options(session, None, Transaction.payment_status), format_func=lambda x: x or "Tümü")
    return AnalyticsFilters(start, end, period, tour.id if tour else None, tour_type, channel.id if channel else None, person.id if person else None, country, supplier.id if supplier else None, hotel.id if hotel else None, restaurant.id if restaurant else None, guide.id if guide else None, currency, booking_status, payment_status)


def _format_kpi(key, value):
    if value is None: return "Yeterli veri yok"
    if key in MONEY_KEYS: return format_currency(value)
    if key in PERCENT_KEYS: return f"%{value:,.1f}"
    return f"{value:,.0f}"


def _kpi_cards(current, previous):
    for offset in range(0, len(KPI_LABELS), 4):
        columns = st.columns(4)
        for column, key in zip(columns, list(KPI_LABELS)[offset:offset + 4]):
            now, before = current.get(key), previous.get(key)
            if now is None or before is None:
                delta, note = None, "Karşılaştırma için yeterli veri yok."
            elif before == 0:
                delta, note = None, "Önceki dönem sıfır olduğu için yüzde değişim hesaplanmadı."
            else:
                absolute = now - before; change = absolute / abs(before) * 100
                delta = f"{absolute:,.1f} · %{change:,.1f}"
                note = f"{KPI_LABELS[key]} önceki döneme göre %{abs(change):,.1f} {'arttı' if change >= 0 else 'azaldı'}."
            column.metric(KPI_LABELS[key], _format_kpi(key, now), delta)
            column.caption(f"Önceki dönem: {_format_kpi(key, before)}. {note}")


def _data_quality(snapshot):
    records = snapshot["bookings"] + snapshot["transactions"] + snapshot["payments"]
    problems = []
    for booking in snapshot["bookings"]:
        if not booking.booking_date: problems.append("Eksik rezervasyon tarihi")
        if not booking.currency: problems.append("Eksik para birimi")
        if not booking.tour_id: problems.append("Eksik tur ilişkisi")
    for txn in snapshot["transactions"]:
        if not txn.transaction_date: problems.append("Eksik işlem tarihi")
        if not txn.currency: problems.append("Eksik para birimi")
        if txn.subtotal is not None and txn.tax_total is not None and txn.grand_total is not None and abs(float(txn.subtotal + txn.tax_total - txn.grand_total)) > 1: problems.append("Tutarsız fatura toplamı")
    for payment in snapshot["payments"]:
        if not payment.supplier_id: problems.append("Eksik tedarikçi ilişkisi")
        if not payment.currency: problems.append("Eksik para birimi")
    ratio = len(problems) / max(len(records), 1)
    score = "İyi" if ratio < .05 else ("Geliştirilmeli" if ratio < .2 else "Kritik")
    return score, pd.Series(problems).value_counts().rename_axis("Sorun").reset_index(name="Kayıt") if problems else pd.DataFrame(columns=["Sorun", "Kayıt"])


def render_management_analytics():
    page_header("Yönetim Analitiği", "Satış, maliyet, kârlılık, tahsilat ve operasyon performansını dönemsel olarak inceleyin.")
    session = Session()
    try:
        filters = _filters(session)
        snapshot = AnalyticsQueryService.snapshot(session, filters)
        cache_token = session.query(Booking).count() + session.query(Transaction).count() + len(snapshot["payments"]) + len(snapshot["reconciliations"])
        current_metrics, previous_metrics, monthly = cached_financial_analytics(asdict(filters), cache_token)
        quality, quality_frame = _data_quality(snapshot)
        st.info(f"Veri kalitesi: **{quality}** · Eksik değerler finansal tutar gibi yorumlanmıyor; yalnızca anlamlı olduğunda sıfır kullanılıyor.")
        if not quality_frame.empty:
            with st.expander("Veri kalitesi sorunlarını göster"): st.dataframe(quality_frame, hide_index=True)

        section_header("Yönetici Göstergeleri")
        _kpi_cards(current_metrics, previous_metrics)

        tour_frame = TourAnalyticsService.profitability(session, filters)
        supplier_frame = SupplierAnalyticsService.performance(session, filters)
        rec_metrics, rec_status, rec_differences = ReconciliationAnalyticsService.summary(session, filters)

        section_header("Aylık Gelir, Gider ve Net Kâr")
        if monthly.empty: empty_state("Yeterli veri yok", "Seçilen dönemde finansal hareket bulunamadı.")
        else:
            melted = monthly.melt("Ay", value_vars=["Gelir", "Gider", "Net Kâr"], var_name="Gösterge", value_name="Tutar")
            st.plotly_chart(px.line(melted, x="Ay", y="Tutar", color="Gösterge", markers=True), use_container_width=True)
            with st.expander("Kayıtları Gör"): st.dataframe(monthly, hide_index=True, use_container_width=True)

        section_header("Rezervasyon ve Satış Performansı")
        reservation = ReservationAnalyticsService.summary(snapshot["bookings"])
        reservation_cols = st.columns(5)
        for col, label, key, suffix in zip(reservation_cols, ["Rezervasyon", "Onay Oranı", "İptal Oranı", "Ortalama Tutar", "Ortalama Lead Time"], ["count", "confirmed_rate", "cancellation_rate", "average_value", "average_lead_days"], ["", "%", "%", "TRY", " gün"]):
            value = reservation[key]
            col.metric(label, "Yeterli veri yok" if value is None else (format_currency(value) if suffix == "TRY" else f"{value:,.1f}{suffix}"))
        channel_names = {row.id: row.name for row in session.query(SalesChannel).all()}
        booking_rows = [{"Tarih": row.booking_date.date(), "Satış Kanalı": channel_names.get(row.sales_channel_id, "Belirtilmemiş"), "Gelir": float(row.grand_total or 0), "Rezervasyon": 1} for row in snapshot["bookings"] if row.booking_date]
        if booking_rows:
            booking_frame = pd.DataFrame(booking_rows)
            by_channel = booking_frame.groupby("Satış Kanalı", as_index=False)[["Gelir", "Rezervasyon"]].sum()
            left, right = st.columns(2)
            left.plotly_chart(px.bar(by_channel, x="Satış Kanalı", y="Gelir", title="Satış Kanalına Göre Gelir"), use_container_width=True)
            right.plotly_chart(px.line(booking_frame.groupby("Tarih", as_index=False)["Rezervasyon"].sum(), x="Tarih", y="Rezervasyon", markers=True, title="Zaman İçinde Rezervasyon"), use_container_width=True)

        section_header("Tur Kârlılığı")
        if tour_frame.empty: empty_state("Tur verisi yok", "Filtrelere uyan tur ve rezervasyon bulunamadı.")
        else:
            chart_frame = tour_frame.sort_values("Net Kâr", ascending=False).head(15)
            st.plotly_chart(px.bar(chart_frame, x="Tur", y=["Toplam Gelir", "Doğrudan Maliyet", "Net Kâr"], barmode="group"), use_container_width=True)
            losses = tour_frame[tour_frame["Net Kâr"] < 0]
            if not losses.empty: st.error(f"{len(losses)} tur zarar ediyor. Aşağıdaki ayrıntılı tabloda kırmızı işaretli kayıtları inceleyin.")
            st.dataframe(tour_frame.sort_values("Net Kâr", ascending=False), hide_index=True, use_container_width=True)

        section_header("Tedarikçi Harcaması ve Risk")
        if supplier_frame.empty: empty_state("Tedarikçi verisi yok", "Seçilen dönemde tedarikçi ödeme kaydı bulunamadı.")
        else:
            left, right = st.columns(2)
            left.plotly_chart(px.bar(supplier_frame.sort_values("Fatura Toplamı", ascending=False), x="Tedarikçi", y="Fatura Toplamı", color="Risk"), use_container_width=True)
            right.plotly_chart(px.scatter(supplier_frame, x="Uyuşmazlık %", y="Ortalama Gecikme", size="Fatura Toplamı", color="Risk", hover_name="Tedarikçi"), use_container_width=True)
            with st.expander("Tedarikçi kayıtlarını ve risk gerekçelerini gör"): st.dataframe(supplier_frame, hide_index=True, use_container_width=True)

        section_header("Belge Mutabakatı İstatistikleri")
        cols = st.columns(6)
        for col, label, key in zip(cols, ["İncelenen", "Tam Eşleşen", "Kritik", "Eşleşmeyen", "Toplam Fark", "Önlenen Fazla Ödeme"], ["documents", "exact", "critical", "unmatched", "discrepancy", "prevented_overpayment"]): col.metric(label, format_currency(rec_metrics[key]) if key in {"discrepancy", "prevented_overpayment"} else rec_metrics[key])
        left, right = st.columns(2)
        if not rec_status.empty: left.plotly_chart(px.pie(rec_status, names="Durum", values="Belge Sayısı", hole=.45), use_container_width=True)
        if not rec_differences.empty: right.plotly_chart(px.bar(rec_differences.sort_values("Sayı"), x="Sayı", y="Sorun Alanı", orientation="h"), use_container_width=True)

        section_header("Açıklamalı İstatistikler")
        statistics = {
            "Rezervasyon Tutarı": StatisticalSummaryService.describe([row.grand_total for row in snapshot["bookings"]], "Rezervasyon tutarı"),
            "Yolcu Sayısı": StatisticalSummaryService.describe([row.passenger_count for row in snapshot["bookings"]], "Yolcu sayısı"),
            "Tur Marjı": StatisticalSummaryService.describe(tour_frame.get("Kâr Marjı %", []), "Tur kâr marjı"),
            "Tedarikçi Fatura Tutarı": StatisticalSummaryService.describe(supplier_frame.get("Fatura Toplamı", []), "Tedarikçi faturası"),
            "Belge Farkı": StatisticalSummaryService.describe([row.difference_amount for row in snapshot["reconciliations"]], "Belge farkı"),
        }
        for label, values in statistics.items(): st.write(f"**{label}:** {values['message']}")
        with st.expander("İstatistiksel Ayrıntılar"):
            detail = pd.DataFrame([{"Gösterge": key, **value} for key, value in statistics.items()])
            st.dataframe(detail, hide_index=True, use_container_width=True)

        anomalies = AnomalyDetectionService.iqr([row.grand_total for row in snapshot["bookings"]], [row.booking_number for row in snapshot["bookings"]], "Rezervasyon tutarı")
        section_header("Deterministik Anomali Kontrolü")
        if anomalies: st.dataframe(pd.DataFrame(anomalies), hide_index=True, use_container_width=True)
        else: st.info("IQR kontrolünde anomali bulunmadı veya güvenilir aralık için yeterli veri yok.")

        forecast = ForecastingService.next_30_days(session)
        section_header("Önümüzdeki 30 Gün")
        cols = st.columns(4)
        for col, label, key in zip(cols, ["Kesin Tahsilat", "Beklenen Tahsilat", "Kesin Ödeme", "Net Nakit Pozisyonu"], ["confirmed_collections", "expected_collections", "confirmed_payments", "net_position"]): col.metric(label, format_currency(forecast[key]))
        st.caption(f"Varsayım: {forecast['method']} Güven düzeyi: {forecast['confidence']}.")
        if forecast["net_position"] < 0: st.error("Önümüzdeki 30 günde beklenen nakit çıkışı girişten yüksek. Ödeme takvimi incelenmeli.")

        insights = ManagementInsightService.build(current_metrics, previous_metrics, supplier_frame, rec_metrics)
        section_header("Yönetim İçgörüleri")
        for insight in insights: st.info(insight)

        section_header("Cari Hesap Analitiği")
        accounts=session.query(CurrentAccount).all();movements=session.query(CurrentAccountMovement).all();open_items=session.query(OpenItem).filter(OpenItem.remaining_amount>0).all();customer_ids={x.id for x in accounts if x.customer_id};supplier_ids={x.id for x in accounts if x.supplier_id};receivables=sum((row.remaining_amount for row in open_items if row.account_id in customer_ids),0);payables=sum((row.remaining_amount for row in open_items if row.account_id in supplier_ids),0);overdue=sum((row.remaining_amount for row in open_items if row.due_date and row.due_date.date()<date.today()),0);disputed=session.query(AccountReconciliation).filter_by(status="Mutabık Değil").all();account_cols=st.columns(5);account_cols[0].metric("Toplam Alacak",format_currency(receivables));account_cols[1].metric("Toplam Borç",format_currency(payables));account_cols[2].metric("Gecikmiş Oran",f"%{(float(overdue/(receivables+payables))*100 if receivables+payables else 0):.1f}");account_cols[3].metric("Cari Hareket",len(movements));account_cols[4].metric("İhtilaflı Tutar",format_currency(sum((abs(x.closing_balance) for x in disputed),0)))
        balance_rows=[]
        for account in accounts:
            rows=[x for x in movements if x.account_id==account.id];balance_rows.append({"Cari":account.name,"Tür":account.account_type,"Bakiye":float(sum((x.debit-x.credit for x in rows),0))})
        if balance_rows:st.plotly_chart(px.bar(pd.DataFrame(balance_rows).sort_values("Bakiye",ascending=False).head(20),x="Cari",y="Bakiye",color="Tür",title="En Yüksek Cari Bakiyeler"),use_container_width=True)

        section_header("Dışa Aktarım")
        tables = {"Finansal Trend": monthly, "Tur Karliligi": tour_frame, "Tedarikciler": supplier_frame, "Mutabakat Durumlari": rec_status, "Mutabakat Sorunlari": rec_differences, "Anomaliler": pd.DataFrame(anomalies)}
        export_cols = st.columns(3)
        export_cols[0].download_button("Analizleri Excel İndir", AnalyticsExportService.excel(tables), "yonetim-analitigi.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        export_cols[1].download_button("Filtreli Finans Tablosu CSV", AnalyticsExportService.csv(monthly), "finansal-trend.csv", "text/csv")
        pdf = AnalyticsExportService.executive_pdf("Yonetim Analitigi", filters, {KPI_LABELS[key]: _format_kpi(key, value) for key, value in current_metrics.items()}, insights)
        export_cols[2].download_button("Tek Sayfa Yönetici Özeti PDF", pdf, "yonetici-ozeti.pdf", "application/pdf")
    finally:
        session.close()
