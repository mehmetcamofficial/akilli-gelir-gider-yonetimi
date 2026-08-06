import streamlit as st
import pandas as pd
from sqlalchemy.orm import sessionmaker
from datetime import date
from database.db import engine
from database.models import Booking, Collection, SupplierPayment, Transaction


def render_reports():
    st.header("Raporlar")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Rapor Oluştur")
    today = date.today()
    start_date = st.date_input("Başlangıç Tarihi", value=today.replace(day=1))
    end_date = st.date_input("Bitiş Tarihi", value=today)

    if start_date > end_date:
        st.error("Başlangıç tarihi bitiş tarihinden önce olmalıdır.")
        session.close()
        return

    if st.button("Rezervasyon Raporunu İndir"):
        bookings = session.query(Booking).filter(Booking.booking_date >= start_date).filter(Booking.booking_date <= end_date).all()
        df = pd.DataFrame([
            {
                "Rezervasyon No": b.booking_number,
                "Müşteri": b.customer.first_name + " " + (b.customer.last_name or "") if b.customer else "-",
                "Tur": b.tour.name if b.tour else "-",
                "Toplam": float(b.grand_total or 0),
                "Durum": b.booking_status or "-",
                "Operasyon": b.operation_status or "-",
            }
            for b in bookings
        ])
        st.download_button("Rezervasyon CSV", data=df.to_csv(index=False).encode('utf-8'), file_name="booking_report.csv", mime="text/csv")

    if st.button("Tahsilat Raporunu İndir"):
        collections = session.query(Collection).filter(Collection.collection_date >= start_date).filter(Collection.collection_date <= end_date).all()
        df = pd.DataFrame([
            {
                "Tahsilat No": c.id,
                "Rezervasyon No": c.booking.booking_number if c.booking else "-",
                "Müşteri": c.booking.customer.first_name + " " + (c.booking.customer.last_name or "") if c.booking and c.booking.customer else "-",
                "Tutar": float(c.amount or 0),
                "Hesap": c.account_name or "-",
                "Ödeme Yöntemi": c.payment_method or "-",
            }
            for c in collections
        ])
        st.download_button("Tahsilat CSV", data=df.to_csv(index=False).encode('utf-8'), file_name="collection_report.csv", mime="text/csv")

    if st.button("Tedarikçi Ödemeleri Raporu"):
        supplier_payments = session.query(SupplierPayment).filter(SupplierPayment.service_date >= start_date).filter(SupplierPayment.service_date <= end_date).all()
        df = pd.DataFrame([
            {
                "Tedarikçi": sp.supplier.name if sp.supplier else "-",
                "Fatura": sp.invoice_reference or "-",
                "Toplam Borç": float(sp.total_debt or 0),
                "Kalan": float(sp.remaining_amount or 0),
                "Durum": sp.payment_status or "-",
            }
            for sp in supplier_payments
        ])
        st.download_button("Tedarikçi Ödeme CSV", data=df.to_csv(index=False).encode('utf-8'), file_name="supplier_payments_report.csv", mime="text/csv")

    if st.button("Finans İşlemleri Raporu"):
        txns = session.query(Transaction).filter(Transaction.transaction_date >= start_date).filter(Transaction.transaction_date <= end_date).all()
        df = pd.DataFrame([
            {
                "No": t.invoice_number or t.id,
                "Tür": t.transaction_type,
                "Tutar": float(t.grand_total or 0),
                "Durum": t.payment_status or "-",
                "Firma/Kişi": t.party_name or "-",
            }
            for t in txns
        ])
        st.download_button("Finans CSV", data=df.to_csv(index=False).encode('utf-8'), file_name="transaction_report.csv", mime="text/csv")

    session.close()
