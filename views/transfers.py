import streamlit as st
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Transfer, Booking, Tour, Supplier


def render_transfers():
    st.header("Transferler")
    Session = sessionmaker(bind=engine)
    session = Session()

    bookings = session.query(Booking).order_by(Booking.booking_date.desc()).all()
    tours = session.query(Tour).order_by(Tour.name).all()
    suppliers = session.query(Supplier).order_by(Supplier.name).all()

    booking_options = {"-": None}
    booking_options.update({f"{b.id}": b.booking_number for b in bookings})
    tour_options = {"-": None}
    tour_options.update({f"{t.id}": t.name for t in tours})
    supplier_options = {"-": None}
    supplier_options.update({f"{s.id}": s.name for s in suppliers})

    with st.form("transfer_form"):
        booking_choice = st.selectbox("Rezervasyon", list(booking_options.values()), format_func=lambda x: x or "-")
        tour_choice = st.selectbox("Tur", list(tour_options.values()), format_func=lambda x: x or "-")
        transfer_type = st.text_input("Transfer Türü")
        pickup_location = st.text_input("Alış Noktası")
        dropoff_location = st.text_input("Bırakış Noktası")
        flight_number = st.text_input("Uçuş No")
        flight_time = st.datetime_input("Uçuş Saati", value=datetime.utcnow())
        pickup_time = st.datetime_input("Transfer Saati", value=datetime.utcnow())
        passenger_count = st.number_input("Yolcu Sayısı", min_value=0, value=1, step=1)
        vehicle_type = st.text_input("Araç Türü")
        vehicle_plate = st.text_input("Plaka")
        driver = st.text_input("Şoför")
        supplier_choice = st.selectbox("Tedarikçi", list(supplier_options.values()), format_func=lambda x: x or "-")
        purchase_cost = st.number_input("Alış Maliyeti", min_value=0.0, value=0.0, step=0.1)
        sale_price = st.number_input("Satış Fiyatı", min_value=0.0, value=0.0, step=0.1)
        payment_status = st.selectbox("Ödeme Durumu", ["Beklemede", "Ödendi", "Kısmen ödendi"])
        operation_status = st.text_input("Operasyon Durumu", value="Planlandı")
        notes = st.text_area("Notlar")
        submitted = st.form_submit_button("Transfer Kaydet")

    if submitted:
        try:
            booking_id = None
            tour_id = None
            supplier_id = None
            for k, v in booking_options.items():
                if v == booking_choice:
                    booking_id = int(k) if k != "-" else None
            for k, v in tour_options.items():
                if v == tour_choice:
                    tour_id = int(k) if k != "-" else None
            for k, v in supplier_options.items():
                if v == supplier_choice:
                    supplier_id = int(k) if k != "-" else None

            transfer = Transfer(
                booking_id=booking_id,
                tour_id=tour_id,
                transfer_type=transfer_type or None,
                pickup_location=pickup_location or None,
                dropoff_location=dropoff_location or None,
                flight_number=flight_number or None,
                flight_time=flight_time,
                pickup_time=pickup_time,
                passenger_count=passenger_count,
                vehicle_type=vehicle_type or None,
                vehicle_plate=vehicle_plate or None,
                driver=driver or None,
                supplier_id=supplier_id,
                purchase_cost=Decimal(str(purchase_cost)),
                sale_price=Decimal(str(sale_price)),
                payment_status=payment_status,
                operation_status=operation_status or None,
                notes=notes or None,
            )
            session.add(transfer)
            session.commit()
            st.success("Transfer kaydedildi.")
        except Exception as e:
            st.error(f"Transfer kaydederken hata oluştu: {e}")

    st.markdown("---")
    st.subheader("Transfer Listesi")
    transfers = session.query(Transfer).order_by(Transfer.pickup_time.desc()).limit(100).all()
    if transfers:
        for t in transfers:
            st.write(f"{t.id} | {t.transfer_type or '-'} | {t.pickup_location or '-'} → {t.dropoff_location or '-'} | Yolcu: {t.passenger_count} | Durum: {t.operation_status or '-'}")
    else:
        st.info("Henüz transfer kaydı yok.")

    session.close()
