import os
import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Booking, Transaction, Collection, SupplierPayment, Customer, Supplier, Tour


def render_control_center():
    st.header("Kontrol Merkezi")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Veritabanı Durumu")
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "app.db")
    if os.path.exists(db_path):
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        st.write(f"Veritabanı yolu: `{db_path}`")
        st.write(f"Dosya boyutu: {size_mb:.2f} MB")
    else:
        st.warning("Veritabanı dosyası bulunamadı.")

    st.markdown("---")
    st.subheader("Sistem Özeti")
    counts = {
        "Rezervasyon": session.query(Booking).count(),
        "Finans İşlemi": session.query(Transaction).count(),
        "Tahsilat": session.query(Collection).count(),
        "Tedarikçi Ödeme": session.query(SupplierPayment).count(),
        "Müşteri": session.query(Customer).count(),
        "Tedarikçi": session.query(Supplier).count(),
        "Tur": session.query(Tour).count(),
    }
    for label, count in counts.items():
        st.metric(label, count)

    st.markdown("---")
    st.subheader("Uyarılar")
    overdue_count = session.query(Booking).filter(Booking.remaining_amount > 0).count()
    if overdue_count > 0:
        st.warning(f"{overdue_count} adet bekleyen rezervasyon ödemesi var.")
    else:
        st.success("Bekleyen rezervasyon ödemesi yok.")

    session.close()
