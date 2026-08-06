import streamlit as st
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Collection, Booking, Customer, Staff


def render_collections():
    st.header("Tahsilatlar")
    Session = sessionmaker(bind=engine)
    session = Session()

    bookings = session.query(Booking).order_by(Booking.booking_date.desc()).all()
    customers = session.query(Customer).order_by(Customer.first_name, Customer.last_name).all()
    staff = session.query(Staff).order_by(Staff.first_name).all()

    booking_options = {"-": None}
    booking_options.update({f"{b.id}": b.booking_number for b in bookings})
    customer_options = {"-": None}
    customer_options.update({f"{c.id}": f"{c.first_name} {c.last_name}" for c in customers})
    staff_options = {"-": None}
    staff_options.update({f"{s.id}": f"{s.first_name} {s.last_name}" for s in staff})

    with st.form("collection_form"):
        booking_choice = st.selectbox("Rezervasyon", list(booking_options.values()), format_func=lambda x: x or "-")
        customer_choice = st.selectbox("Müşteri", list(customer_options.values()), format_func=lambda x: x or "-")
        collection_date = st.date_input("Tahsilat Tarihi", value=date.today())
        amount = st.number_input("Tutar", min_value=0.0, value=0.0, step=0.1)
        currency = st.text_input("Para Birimi", value="TRY")
        payment_method = st.text_input("Ödeme Yöntemi", value="Nakit")
        account_name = st.text_input("Hesap Adı", value="Kasa")
        transaction_reference = st.text_input("İşlem Referansı")
        receipt_number = st.text_input("Makbuz No")
        staff_choice = st.selectbox("Sorumlu Personel", list(staff_options.values()), format_func=lambda x: x or "-")
        notes = st.text_area("Notlar")
        submitted = st.form_submit_button("Tahsilat Kaydet")

    if submitted:
        try:
            booking_id = None
            customer_id = None
            staff_id = None
            for k, v in booking_options.items():
                if v == booking_choice:
                    booking_id = int(k) if k != "-" else None
            for k, v in customer_options.items():
                if v == customer_choice:
                    customer_id = int(k) if k != "-" else None
            for k, v in staff_options.items():
                if v == staff_choice:
                    staff_id = int(k) if k != "-" else None

            col = Collection(
                booking_id=booking_id or 0,
                customer_id=customer_id,
                collection_date=datetime.combine(collection_date, datetime.min.time()),
                amount=Decimal(str(amount)),
                currency=currency,
                exchange_rate=Decimal('1.0'),
                amount_in_tl=Decimal(str(amount)),
                payment_method=payment_method,
                account_name=account_name,
                transaction_reference=transaction_reference,
                receipt_number=receipt_number,
                staff_id=staff_id,
                notes=notes,
            )
            session.add(col)
            session.commit()
            st.success("Tahsilat kaydedildi.")
        except Exception as e:
            st.error(f"Tahsilat kaydederken hata oluştu: {e}")

    st.markdown("---")
    st.subheader("Son Tahsilatlar")
    collections = session.query(Collection).order_by(Collection.collection_date.desc()).limit(30).all()
    if collections:
        for c in collections:
            st.write(f"{c.collection_date.date()} | {c.amount:,.2f} {c.currency} | {c.payment_method} | {c.account_name}")
    else:
        st.info("Henüz tahsilat kaydı yok.")

    session.close()
