import streamlit as st
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Customer


def render_customers():
    st.header("Müşteriler ve Yolcular")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Yeni Müşteri Ekle")
    with st.form("customer_form"):
        first_name = st.text_input("Ad")
        last_name = st.text_input("Soyad")
        company_name = st.text_input("Şirket")
        nationality = st.text_input("Uyruk")
        document_number = st.text_input("Kimlik / Pasaport No")
        phone = st.text_input("Telefon")
        email = st.text_input("E-posta")
        address = st.text_area("Adres")
        birth_date = st.date_input("Doğum Tarihi", value=datetime.utcnow().date())
        language = st.text_input("Dil")
        emergency_contact = st.text_input("Acil Durum İletişim")
        billing_info = st.text_area("Fatura Bilgisi")
        tax_number = st.text_input("Vergi No")
        notes = st.text_area("Notlar")
        submitted = st.form_submit_button("Müşteri Kaydet")

    if submitted:
        if not first_name:
            st.error("Müşteri adı zorunludur.")
        else:
            customer = Customer(
                first_name=first_name,
                last_name=last_name,
                company_name=company_name or None,
                nationality=nationality or None,
                document_number=document_number or None,
                phone=phone or None,
                email=email or None,
                address=address or None,
                birth_date=datetime.combine(birth_date, datetime.min.time()),
                language=language or None,
                emergency_contact=emergency_contact or None,
                billing_info=billing_info or None,
                tax_number=tax_number or None,
                notes=notes or None,
                kvkk_confirmed=False,
            )
            session.add(customer)
            session.commit()
            st.success("Müşteri kaydedildi.")

    st.markdown("---")
    st.subheader("Müşteri Listesi")
    customers = session.query(Customer).order_by(Customer.first_name, Customer.last_name).limit(100).all()
    if customers:
        for c in customers:
            st.write(f"{c.id} - {c.first_name} {c.last_name or ''} | {c.email or '-'} | {c.phone or '-'} | {c.nationality or '-'}")
    else:
        st.info("Henüz müşteri kaydı yok.")

    session.close()
