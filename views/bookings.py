import streamlit as st
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Booking, Customer, Tour, Staff, SalesChannel
from utils.ui import empty_state


def render_bookings():
    st.header("Rezervasyonlar")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Yeni Rezervasyon Oluştur")
    customers = session.query(Customer).order_by(Customer.first_name, Customer.last_name).all()
    tours = session.query(Tour).order_by(Tour.name).all()
    staff = session.query(Staff).order_by(Staff.first_name).all()
    channels = session.query(SalesChannel).order_by(SalesChannel.name).all()

    customer_options = {"-": None}
    customer_options.update({f"{c.id}": f"{c.first_name} {c.last_name}" for c in customers})
    tour_options = {"-": None}
    tour_options.update({f"{t.id}": f"{t.name}" for t in tours})
    staff_options = {"-": None}
    staff_options.update({f"{s.id}": f"{s.first_name} {s.last_name}" for s in staff})
    channel_options = {"-": None}
    channel_options.update({f"{c.id}": c.name for c in channels})

    with st.form("booking_form"):
        booking_number = st.text_input("Rezervasyon Numarası")
        booking_date = st.date_input("Rezervasyon Tarihi", value=date.today())
        service_start = st.date_input("Hizmet Başlangıç Tarihi", value=date.today())
        service_end = st.date_input("Hizmet Bitiş Tarihi", value=date.today())
        customer_choice = st.selectbox("Müşteri", list(customer_options.values()), format_func=lambda v: v or "-")
        tour_choice = st.selectbox("Tur", list(tour_options.values()), format_func=lambda v: v or "-")
        sales_channel_choice = st.selectbox("Satış Kanalı", list(channel_options.values()), format_func=lambda v: v or "-")
        sales_person_choice = st.selectbox("Satış Sorumlusu", list(staff_options.values()), format_func=lambda v: v or "-")
        guide_choice = st.selectbox("Rehber", list(staff_options.values()), format_func=lambda v: v or "-")
        adult_count = st.number_input("Yetişkin", min_value=0, value=1, step=1)
        child_count = st.number_input("Çocuk", min_value=0, value=0, step=1)
        infant_count = st.number_input("Bebek", min_value=0, value=0, step=1)
        unit_price = st.number_input("Kişi Başına Birim Fiyat", min_value=0.0, value=0.0, step=0.1)
        discount_amount = st.number_input("İskonto", min_value=0.0, value=0.0, step=0.1)
        commission_amount = st.number_input("Komisyon", min_value=0.0, value=0.0, step=0.1)
        tax_amount = st.number_input("Vergi", min_value=0.0, value=0.0, step=0.1)
        booking_status = st.selectbox("Rezervasyon Durumu", ["Planlandı", "Kısmen ödendi", "Ödendi", "İptal edildi"])
        operation_status = st.text_input("Operasyon Durumu", value="Planlandı")
        notes = st.text_area("Notlar")
        submitted = st.form_submit_button("Kaydet")

    if submitted:
        try:
            customer_id = None
            tour_id = None
            sales_channel_id = None
            sales_person_id = None
            guide_id = None
            for k, v in customer_options.items():
                if v == customer_choice:
                    customer_id = int(k) if k != "-" else None
            for k, v in tour_options.items():
                if v == tour_choice:
                    tour_id = int(k) if k != "-" else None
            for k, v in channel_options.items():
                if v == sales_channel_choice:
                    sales_channel_id = int(k) if k != "-" else None
            for k, v in staff_options.items():
                if v == sales_person_choice:
                    sales_person_id = int(k) if k != "-" else None
            for k, v in staff_options.items():
                if v == guide_choice:
                    guide_id = int(k) if k != "-" else None

            total_price = Decimal(str(unit_price)) * Decimal(str(adult_count + child_count + infant_count))
            grand_total = total_price - Decimal(str(discount_amount)) + Decimal(str(tax_amount))
            booking = Booking(
                booking_number=booking_number or f"BK-{int(datetime.utcnow().timestamp())}",
                booking_date=datetime.combine(booking_date, datetime.min.time()),
                service_start_date=datetime.combine(service_start, datetime.min.time()),
                service_end_date=datetime.combine(service_end, datetime.min.time()),
                tour_id=tour_id,
                booking_type="Tur Rezervasyonu",
                customer_id=customer_id,
                passenger_count=adult_count + child_count + infant_count,
                adult_count=adult_count,
                child_count=child_count,
                infant_count=infant_count,
                sales_channel_id=sales_channel_id,
                sales_person_id=sales_person_id,
                guide_id=guide_id,
                currency="TRY",
                exchange_rate=Decimal('1.0'),
                unit_price=Decimal(str(unit_price)),
                total_price=total_price,
                discount_amount=Decimal(str(discount_amount)),
                commission_amount=Decimal(str(commission_amount)),
                tax_amount=Decimal(str(tax_amount)),
                grand_total=grand_total,
                deposit_amount=Decimal('0.00'),
                collected_total=Decimal('0.00'),
                remaining_amount=grand_total,
                payment_method="",
                final_payment_date=None,
                booking_status=booking_status,
                operation_status=operation_status,
                voucher_number=None,
                notes=notes,
            )
            session.add(booking)
            session.commit()
            st.success("Rezervasyon kaydedildi.")
        except Exception as e:
            st.error(f"Rezervasyon kaydederken hata oluştu: {e}")

    st.markdown("---")
    st.subheader("Mevcut Rezervasyonlar")
    bookings = session.query(Booking).order_by(Booking.booking_date.desc()).limit(30).all()
    if bookings:
        for b in bookings:
            st.write(f"{b.booking_number} | {b.booking_status} | {b.service_start_date.date() if b.service_start_date else '-'} | Toplam: {b.grand_total:,.2f} ₺")
    else:
        empty_state(
            "Rezervasyon bulunamadı",
            "Rezervasyon ekleyerek acente operasyonunuzu izleyebilir ve raporları doldurabilirsiniz.",
        )

    session.close()
