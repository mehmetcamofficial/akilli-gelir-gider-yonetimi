import streamlit as st
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Supplier
from utils.ui import empty_state


def render_suppliers():
    st.header("Tedarikçiler")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Yeni Tedarikçi Ekle")
    with st.form("supplier_form"):
        name = st.text_input("Tedarikçi Adı")
        supplier_type = st.text_input("Tedarikçi Türü")
        contact_person = st.text_input("İlgili Kişi")
        tax_office = st.text_input("Vergi Dairesi")
        tax_number = st.text_input("Vergi No")
        phone = st.text_input("Telefon")
        email = st.text_input("E-posta")
        address = st.text_area("Adres")
        iban = st.text_input("IBAN")
        currency = st.text_input("Para Birimi", value="TRY")
        payment_terms = st.text_input("Ödeme Koşulları")
        notes = st.text_area("Notlar")
        submitted = st.form_submit_button("Tedarikçi Kaydet")

    if submitted:
        if not name:
            st.error("Tedarikçi adı zorunludur.")
        else:
            supplier = Supplier(
                name=name,
                supplier_type=supplier_type or None,
                contact_person=contact_person or None,
                tax_office=tax_office or None,
                tax_number=tax_number or None,
                phone=phone or None,
                email=email or None,
                address=address or None,
                iban=iban or None,
                currency=currency or "TRY",
                payment_terms=payment_terms or None,
                notes=notes or None,
            )
            session.add(supplier)
            session.commit()
            st.success("Tedarikçi kaydedildi.")

    st.markdown("---")
    st.subheader("Tedarikçi Listesi")
    suppliers = session.query(Supplier).order_by(Supplier.name).limit(100).all()
    if suppliers:
        for s in suppliers:
            st.write(f"{s.id} - {s.name} | {s.supplier_type or '-'} | {s.contact_person or '-'} | {s.phone or '-'}")
    else:
        empty_state(
            "Tedarikçi kaydı yok",
            "Tedarikçi ekleyerek borç ve ödeme süreçlerinizi düzenleyin.",
        )

    session.close()
