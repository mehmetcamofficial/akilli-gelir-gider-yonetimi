import streamlit as st
from datetime import datetime
from decimal import Decimal
from database.db import engine
from sqlalchemy.orm import sessionmaker
from database.models import Transaction, Category
from services.storage_service import save_uploaded_file


def show():
    st.header("Gelir ve Gider Kaydı")
    Session = sessionmaker(bind=engine)
    session = Session()

    with st.form("txn_form"):
        ttype = st.selectbox("İşlem Türü", ["income", "expense"], format_func=lambda x: "Gelir" if x=="income" else "Gider")
        transaction_date = st.date_input("İşlem Tarihi", value=datetime.utcnow().date())
        invoice_number = st.text_input("Fatura Numarası")
        description = st.text_area("Açıklama")
        party = st.text_input("Firma / Kişi")
        category = st.selectbox("Kategori", [c.name for c in session.query(Category).all()] or ["Diğer"])
        subtotal = st.number_input("KDV Hariç Tutar", min_value=0.0, value=0.0, step=1.0)
        tax = st.number_input("KDV Tutarı", min_value=0.0, value=0.0, step=1.0)
        grand = st.number_input("Genel Toplam", min_value=0.0, value=0.0, step=1.0)
        uploaded_file = st.file_uploader("Belge Yükle (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"]) 
        submitted = st.form_submit_button("Kaydet")

    if submitted:
        try:
            txn = Transaction(
                transaction_type=ttype,
                transaction_date=datetime.combine(transaction_date, datetime.min.time()),
                invoice_number=invoice_number or None,
                description=description,
                party_name=party or None,
                subtotal=Decimal(str(subtotal)),
                tax_total=Decimal(str(tax)),
                grand_total=Decimal(str(grand)),
                paid_amount=Decimal("0.00"),
                remaining_amount=Decimal(str(grand)),
                payment_status="Ödenmedi",
            )
            session.add(txn)
            session.commit()
            session.refresh(txn)

            if uploaded_file is not None:
                # save file and link
                save_uploaded_file(uploaded_file, "income" if ttype=="income" else "expense", session, transaction_id=txn.id)

            st.success("İşlem kaydedildi.")
        except Exception as e:
            st.error(f"Kaydederken hata oluştu: {e}")
    session.close()
