import streamlit as st
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from database.db import engine
from database.models import Booking, SupplierPayment, Customer, Supplier


def render_accounts():
    st.header("Cari Hesaplar")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Cari Hesap Özetleri")
    total_customer_receivable = session.query(func.coalesce(func.sum(Booking.remaining_amount), 0)).scalar() or 0
    total_supplier_payable = session.query(func.coalesce(func.sum(SupplierPayment.remaining_amount), 0)).scalar() or 0

    col1, col2 = st.columns(2)
    col1.metric("Müşteri Alacakları", f"{total_customer_receivable:,.2f} ₺")
    col2.metric("Tedarikçi Borçları", f"{total_supplier_payable:,.2f} ₺")

    st.markdown("---")
    st.subheader("En Büyük 5 Müşteri Alacağı")
    customer_balances = session.query(
        Customer.first_name,
        Customer.last_name,
        func.coalesce(func.sum(Booking.remaining_amount), 0).label('balance')
    ).join(Booking, Booking.customer_id == Customer.id).group_by(Customer.id).order_by(func.sum(Booking.remaining_amount).desc()).limit(5).all()

    if customer_balances:
        st.table([{"Müşteri": f"{c.first_name} {c.last_name}", "Bakiye": f"{c.balance:,.2f} ₺"} for c in customer_balances])
    else:
        st.info("Henüz alacak kaydı yok.")

    st.subheader("En Büyük 5 Tedarikçi Borcu")
    supplier_balances = session.query(
        Supplier.name,
        func.coalesce(func.sum(SupplierPayment.remaining_amount), 0).label('balance')
    ).join(SupplierPayment, SupplierPayment.supplier_id == Supplier.id).group_by(Supplier.id).order_by(func.sum(SupplierPayment.remaining_amount).desc()).limit(5).all()

    if supplier_balances:
        st.table([{"Tedarikçi": s.name, "Bakiye": f"{s.balance:,.2f} ₺"} for s in supplier_balances])
    else:
        st.info("Henüz tedarikçi borç kaydı yok.")

    session.close()
