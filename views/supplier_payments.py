import streamlit as st
from datetime import date
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import SupplierPayment, Supplier
from utils.ui import page_header, section_header, format_currency, format_date, empty_state


def render_supplier_payments():
    page_header(
        "Tedarikçi Ödemeleri",
        "Tedarikçi ödemelerini ve vade takibini düzenli raporlayın.",
        action_label="Yeni Tedarikçi Ödemesi",
        action_page="Tedarikçi Ödemeleri",
    )

    Session = sessionmaker(bind=engine)
    session = Session()
    today = date.today()

    upcoming = session.query(SupplierPayment).filter(SupplierPayment.due_date != None).filter(SupplierPayment.due_date >= today).order_by(SupplierPayment.due_date.asc()).limit(20).all()
    overdue = session.query(SupplierPayment).filter(SupplierPayment.due_date != None).filter(SupplierPayment.due_date < today).order_by(SupplierPayment.due_date.asc()).limit(20).all()

    if not upcoming and not overdue:
        empty_state(
            "Ödeme planı bulunamadı",
            "Tedarikçi ödemelerini kaydederek hesap akışınızı ve vadeleri kontrol edin.",
        )
        session.close()
        return

    if overdue:
        section_header("Vadesi Geçmiş Ödemeler")
        st.markdown("<div class='table-container'>", unsafe_allow_html=True)
        st.markdown(
            "<table><thead><tr><th>Tedarikçi</th><th>Fatura Ref.</th><th>Vade</th><th>Bakiye</th><th>Durum</th></tr></thead><tbody>",
            unsafe_allow_html=True,
        )
        for payment in overdue:
            supplier = session.get(Supplier, payment.supplier_id) if payment.supplier_id else None
            supplier_name = supplier.name if supplier else '-'
            st.markdown(
                f"<tr><td>{supplier_name}</td>"
                f"<td>{payment.invoice_reference or '-'}</td>"
                f"<td>{format_date(payment.due_date)}</td>"
                f"<td>{format_currency(payment.remaining_amount)}</td>"
                f"<td>{payment.payment_status or 'Bekliyor'}</td></tr>",
                unsafe_allow_html=True,
            )
        st.markdown("</tbody></table>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    if upcoming:
        section_header("Yaklaşan Ödemeler")
        st.markdown("<div class='table-container'>", unsafe_allow_html=True)
        st.markdown(
            "<table><thead><tr><th>Tedarikçi</th><th>Fatura Ref.</th><th>Vade</th><th>Bakiye</th><th>Durum</th></tr></thead><tbody>",
            unsafe_allow_html=True,
        )
        for payment in upcoming:
            supplier = session.get(Supplier, payment.supplier_id) if payment.supplier_id else None
            supplier_name = supplier.name if supplier else '-'
            st.markdown(
                f"<tr><td>{supplier_name}</td>"
                f"<td>{payment.invoice_reference or '-'}</td>"
                f"<td>{format_date(payment.due_date)}</td>"
                f"<td>{format_currency(payment.remaining_amount)}</td>"
                f"<td>{payment.payment_status or 'Bekliyor'}</td></tr>",
                unsafe_allow_html=True,
            )
        st.markdown("</tbody></table>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    session.close()
