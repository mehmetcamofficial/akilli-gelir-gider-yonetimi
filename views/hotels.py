import streamlit as st
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Hotel


def render_hotels():
    st.header("Oteller")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Yeni Otel Ekle")
    with st.form("hotel_form"):
        name = st.text_input("Otel Adı")
        address = st.text_area("Adres")
        phone = st.text_input("Telefon")
        email = st.text_input("E-posta")
        currency = st.text_input("Para Birimi", value="TRY")
        rating = st.text_input("Puan")
        notes = st.text_area("Notlar")
        submitted = st.form_submit_button("Otel Kaydet")

    if submitted:
        if not name:
            st.error("Otel adı zorunludur.")
        else:
            hotel = Hotel(
                name=name,
                address=address or None,
                phone=phone or None,
                email=email or None,
                currency=currency or "TRY",
                rating=rating or None,
                notes=notes or None,
            )
            session.add(hotel)
            session.commit()
            st.success("Otel kaydedildi.")

    st.markdown("---")
    st.subheader("Otel Listesi")
    hotels = session.query(Hotel).order_by(Hotel.name).limit(100).all()
    if hotels:
        for h in hotels:
            st.write(f"{h.id} - {h.name} | {h.address or '-'} | {h.phone or '-'} | {h.email or '-'}")
    else:
        st.info("Henüz otel kaydı yok.")

    session.close()
