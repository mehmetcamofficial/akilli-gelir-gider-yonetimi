import streamlit as st
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from database.db import engine
import pandas as pd
from datetime import date, timedelta
from decimal import Decimal
from database.models import Booking, Tour, Collection, Notification, SupplierPayment, Supplier
import plotly.express as px
from utils.ui import page_header, render_metric_cards, section_header, format_currency, empty_state


def render_dashboard():
    page_header(
        "Genel Bakış",
        "Seyahat acentenizin finansal performansını, rezervasyon sürecini ve nakit akışını tek bir ekranda takip edin.",
    )

    Session = sessionmaker(bind=engine)
    session = Session()

    today = date.today()
    month_start = today.replace(day=1)
    next_30 = today + timedelta(days=30)

    bookings_today = session.query(Booking).filter(Booking.service_start_date != None).filter(func.date(Booking.service_start_date) == today).count()
    bookings_month = session.query(Booking).filter(Booking.booking_date >= month_start).count()
    upcoming_tours = session.query(Booking).filter(Booking.service_start_date != None).filter(Booking.service_start_date <= next_30).count()
    todays_operations = session.query(Booking).filter(Booking.service_start_date != None).filter(func.date(Booking.service_start_date) == today).count()

    total_revenue = session.query(func.coalesce(func.sum(Booking.grand_total), 0)).scalar() or Decimal('0.00')
    total_collected = session.query(func.coalesce(func.sum(Collection.amount_in_tl), 0)).scalar() or Decimal('0.00')
    pending_collection = session.query(func.coalesce(func.sum(Booking.remaining_amount), 0)).scalar() or Decimal('0.00')
    total_supplier_debt = session.query(func.coalesce(func.sum(SupplierPayment.remaining_amount), 0)).scalar() or Decimal('0.00')
    upcoming_supplier_payments = session.query(SupplierPayment).filter(SupplierPayment.due_date != None).filter(SupplierPayment.due_date <= next_30).count()
    overdue_customer_receivables = session.query(func.coalesce(func.sum(Booking.remaining_amount), 0)).filter(Booking.final_payment_date != None).filter(Booking.final_payment_date < today).scalar() or Decimal('0.00')
    overdue_supplier_liabilities = session.query(func.coalesce(func.sum(SupplierPayment.remaining_amount), 0)).filter(SupplierPayment.due_date != None).filter(SupplierPayment.due_date < today).scalar() or Decimal('0.00')
    total_passengers = session.query(func.coalesce(func.sum(Booking.passenger_count), 0)).scalar() or 0
    booking_count = session.query(Booking).count()
    avg_booking_amount = total_revenue / booking_count if booking_count else Decimal('0.00')
    cancelled_bookings = session.query(Booking).filter(Booking.booking_status.ilike('%iptal%')).count()
    tour_capacity = session.query(func.coalesce(func.sum(Tour.capacity), 0)).scalar() or 0
    occupancy_rate = (float(total_passengers) / float(tour_capacity) * 100) if tour_capacity else 0.0
    today_collections = session.query(Booking).filter(func.date(Booking.final_payment_date) == today, Booking.remaining_amount > 0).count()
    week_collections = session.query(Booking).filter(Booking.final_payment_date > today, Booking.final_payment_date <= today + timedelta(days=7), Booking.remaining_amount > 0).count()
    overdue_collections = session.query(Booking).filter(Booking.final_payment_date < today, Booking.remaining_amount > 0).count()
    today_payments = session.query(SupplierPayment).filter(func.date(SupplierPayment.due_date) == today, SupplierPayment.remaining_amount > 0).count()
    week_payments = session.query(SupplierPayment).filter(SupplierPayment.due_date > today, SupplierPayment.due_date <= today + timedelta(days=7), SupplierPayment.remaining_amount > 0).count()
    overdue_payments = session.query(SupplierPayment).filter(SupplierPayment.due_date < today, SupplierPayment.remaining_amount > 0).count()
    pending_reminders = session.query(Notification).filter(Notification.status.in_(["Planlandı", "Gönderime Hazır", "Ertelendi"])).count()

    render_metric_cards([
        {"title":"Bugün Vadesi Gelen Tahsilat","value":today_collections,"note":"Müşteri tahsilatları"},
        {"title":"Önümüzdeki 7 Gün Tahsilat","value":week_collections,"note":"Yaklaşan tahsilatlar"},
        {"title":"Vadesi Geçmiş Tahsilat","value":overdue_collections,"note":"Takip gerektiriyor"},
        {"title":"Bugün Vadesi Gelen Ödeme","value":today_payments,"note":"Tedarikçi ödemeleri"},
        {"title":"Önümüzdeki 7 Gün Ödeme","value":week_payments,"note":"Yaklaşan ödemeler"},
        {"title":"Vadesi Geçmiş Ödeme","value":overdue_payments,"note":"Kontrol gerektiriyor"},
        {"title":"Bekleyen Hatırlatma","value":pending_reminders,"note":"Bildirim merkezinde"},
    ], columns=4)

    render_metric_cards(
        [
            {
                "title": "Bugünkü Rezervasyon",
                "value": f"{bookings_today}",
                "note": "Güncel operasyon yoğunluğu",
            },
            {
                "title": "Bu Ayki Rezervasyon",
                "value": f"{bookings_month}",
                "note": "Ay sonuna kadar planlanan işler",
            },
            {
                "title": "Yaklaşan Turlar",
                "value": f"{upcoming_tours}",
                "note": "Önümüzdeki 30 gün içinde başlayacak",
            },
            {
                "title": "Bugünkü Operasyon",
                "value": f"{todays_operations}",
                "note": "Bugün hizmet verecek tur sayısı",
            },
        ],
        columns=4,
    )

    render_metric_cards(
        [
            {
                "title": "Toplam Satış Geliri",
                "value": format_currency(total_revenue),
                "note": "Rezervasyonlardan elde edilen toplam gelir",
            },
            {
                "title": "Toplam Tahsilat",
                "value": format_currency(total_collected),
                "note": "Gerçekleşen nakit girişleri",
            },
            {
                "title": "Bekleyen Tahsilat",
                "value": format_currency(pending_collection),
                "note": "Müşterilerden alınacak bakiye",
            },
            {
                "title": "Toplam Tedarikçi Borcu",
                "value": format_currency(total_supplier_debt),
                "note": "Tedarikçilere ödemesi beklenen tutar",
            },
        ],
        columns=4,
    )

    render_metric_cards(
        [
            {
                "title": "Yaklaşan Tedarikçi Ödemeleri",
                "value": f"{upcoming_supplier_payments}",
                "note": "30 gün içinde vadesi gelen ödemeler",
            },
            {
                "title": "Vadesi Geçen Alacak",
                "value": format_currency(overdue_customer_receivables),
                "note": "Kaç ödeme gecikti",
            },
            {
                "title": "Vadesi Geçen Borç",
                "value": format_currency(overdue_supplier_liabilities),
                "note": "Tedarikçi borcu gecikmeleri",
            },
            {
                "title": "Toplam Yolcu",
                "value": f"{total_passengers}",
                "note": "Hazırlanan konaklama ve transferler",
            },
        ],
        columns=4,
    )

    render_metric_cards(
        [
            {
                "title": "Ortalama Rezervasyon",
                "value": format_currency(avg_booking_amount),
                "note": "Bir rezervasyonun ortalama değeri",
            },
            {
                "title": "İptal Rezervasyon",
                "value": f"{cancelled_bookings}",
                "note": "Bu dönemde iptal edilen rezervasyonlar",
            },
            {
                "title": "Doluluk Oranı",
                "value": f"{occupancy_rate:.1f} %",
                "note": "Mevcut turun doluluk performansı",
            },
            {
                "title": "Toplam Rezervasyon",
                "value": f"{booking_count}",
                "note": "Sistemde kayıtlı rezervasyon sayısı",
            },
        ],
        columns=4,
    )

    section_header("Finansal Trendler")
    sales_rows = session.query(Booking.booking_date, Booking.grand_total).filter(Booking.booking_date.isnot(None)).all()
    collection_rows = session.query(Collection.collection_date, Collection.amount_in_tl).filter(Collection.collection_date.isnot(None)).all()
    df_sales = pd.DataFrame([{"month": row.booking_date.strftime("%Y-%m"), "revenue": float(row.grand_total or 0)} for row in sales_rows])
    df_pay = pd.DataFrame([{"month": row.collection_date.strftime("%Y-%m"), "collected": float(row.amount_in_tl or 0)} for row in collection_rows])
    if not df_sales.empty: df_sales = df_sales.groupby("month", as_index=False)["revenue"].sum()
    else: df_sales = pd.DataFrame(columns=["month", "revenue"])
    if not df_pay.empty: df_pay = df_pay.groupby("month", as_index=False)["collected"].sum()
    else: df_pay = pd.DataFrame(columns=["month", "collected"])
    if not df_sales.empty or not df_pay.empty:
        df_merge = pd.merge(df_sales, df_pay, on='month', how='outer').fillna(0)
        df_merge = df_merge.sort_values('month')
        fig = px.line(
            df_merge,
            x='month',
            y=['revenue', 'collected'],
            labels={'value': 'TRY', 'month': 'Ay', 'variable': 'Hesap'},
            markers=True,
        )
        fig.update_layout(legend_title_text='Seri', hovermode='x unified')
        st.plotly_chart(fig, use_container_width=True)
    else:
        empty_state(
            "Veri Yetersiz",
            "Aylık satış ve tahsilat trendlerini görmek için rezervasyon veya tahsilat kayıtları ekleyin.",
        )

    section_header("Tur Performansı ve Tedarikçi Etkisi")
    col1, col2 = st.columns([2, 1], gap='large')
    with col1:
        tour_revenues = session.query(Tour.tour_type, func.coalesce(func.sum(Booking.grand_total), 0).label('revenue')).join(Booking, Booking.tour_id == Tour.id).group_by(Tour.tour_type).all()
        df_tour_rev = pd.DataFrame(tour_revenues, columns=['tour_type', 'revenue'])
        if not df_tour_rev.empty:
            fig = px.pie(
                df_tour_rev,
                names='tour_type',
                values='revenue',
                title='Tur Türüne Göre Gelir',
                hole=0.45,
            )
            fig.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig, use_container_width=True)
        else:
            empty_state(
                "Tur Geliri Yok",
                "Tur verisi bulunamadı, yeni rezervasyon ekleyerek raporları canlandırın.",
            )

    with col2:
        top_tours = session.query(Tour.name, func.count(Booking.id).label('bookings')).join(Booking, Booking.tour_id == Tour.id).group_by(Tour.name).order_by(func.count(Booking.id).desc()).limit(8).all()
        df_top_tours = pd.DataFrame(top_tours, columns=['tour', 'bookings'])
        if not df_top_tours.empty:
            st.markdown("<div class='section-box'><div class='section-title'>En Çok Satılan Turlar</div></div>", unsafe_allow_html=True)
            st.bar_chart(df_top_tours.rename(columns={'tour': 'Tur', 'bookings': 'Rezervasyon Sayısı'}).set_index('Tur'))
        else:
            empty_state(
                "Rezervasyon Verisi Yok",
                "Popüler turlar raporu için yeni rezervasyon kaydı ekleyin.",
            )

    section_header("Acentenin En Önemli Tedarikçileri")
    supplier_summary = session.query(Supplier.name, func.coalesce(func.sum(SupplierPayment.total_debt), 0).label('debt')).join(SupplierPayment, SupplierPayment.supplier_id == Supplier.id).group_by(Supplier.name).order_by(func.sum(SupplierPayment.total_debt).desc()).limit(10).all()
    df_suppliers = pd.DataFrame(supplier_summary, columns=['supplier', 'debt'])
    if not df_suppliers.empty:
        df_suppliers['debt'] = df_suppliers['debt'].apply(lambda v: format_currency(v))
        st.dataframe(df_suppliers.rename(columns={'supplier': 'Tedarikçi', 'debt': 'Borç'}))
    else:
        empty_state(
            "Tedarikçi Verisi Yok",
            "Tedarikçi raporu için borç ve ödeme kayıtları gerekir.",
        )

    section_header("Yaklaşan 30 Günlük Nakit Akışı")
    cash_rows = []
    collections_due = session.query(Collection).filter(Collection.collection_date >= today).filter(Collection.collection_date <= next_30).all()
    supplier_due = session.query(SupplierPayment).filter(SupplierPayment.due_date != None).filter(SupplierPayment.due_date >= today).filter(SupplierPayment.due_date <= next_30).all()
    for c in collections_due:
        cash_rows.append({'date': c.collection_date, 'type': 'Tahsilat', 'amount': float(c.amount_in_tl or 0)})
    for s in supplier_due:
        cash_rows.append({'date': s.due_date, 'type': 'Ödeme', 'amount': float(s.remaining_amount or 0)})
    if cash_rows:
        df_cash = pd.DataFrame(cash_rows)
        df_cash['date'] = pd.to_datetime(df_cash['date'])
        cash_pivot = df_cash.groupby(['date', 'type']).agg({'amount': 'sum'}).reset_index()
        cash_chart = cash_pivot.pivot(index='date', columns='type', values='amount').fillna(0)
        st.area_chart(cash_chart)
    else:
        empty_state(
            "Nakit Akışı Boş",
            "Önümüzdeki 30 güne dair tahsilat veya ödeme planı bulunamadı.",
        )

    session.close()
