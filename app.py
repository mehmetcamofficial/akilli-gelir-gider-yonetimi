import streamlit as st
from database.db import init_db
from utils.ui import inject_styles, sidebar_brand, sidebar_menu

from views.dashboard import render_dashboard
from views.income_expense import render_income_expense
from views.invoices import render_invoices
from views.products import render_products
from views.bookings import render_bookings
from views.tours import render_tours
from views.collections import render_collections
from views.supplier_payments import render_supplier_payments
from views.customers import render_customers
from views.suppliers import render_suppliers
from views.hotels import render_hotels
from views.transfers import render_transfers
from views.guides import render_guides
from views.accounts import render_accounts
from views.cash_and_banks import render_cash_and_banks
from views.tour_profitability import render_tour_profitability
from views.reports import render_reports
from views.documents import render_documents
from views.control_center import render_control_center
from views.settings import render_settings
from views.drive_import import render_drive_import


def main():
    st.set_page_config(
        page_title="Seyahat Acentası Finans & Operasyon",
        page_icon="✈️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    inject_styles()
    sidebar_brand()

    selected_page = sidebar_menu(
        [
            ("Genel", ["Genel Bakış"]),
            ("Rezervasyonlar", ["Rezervasyonlar", "Turlar ve Paketler", "Tur Kârlılığı"]),
            ("Finans", ["Gelir ve Giderler", "Faturalar", "Tahsilatlar", "Tedarikçi Ödemeleri"]),
            ("Çekirdek Operasyon", ["Müşteriler ve Yolcular", "Tedarikçiler", "Oteller", "Transferler", "Rehberler"]),
            ("Hesaplar", ["Cari Hesaplar", "Kasa ve Bankalar"]),
            ("Analiz & Rapor", ["Raporlar", "Drive Excel Aktarımı", "Belge Arşivi", "Kontrol Merkezi", "Ayarlar"]),
        ]
    )

    st.sidebar.markdown("---")
    with st.sidebar.expander('Yardım & Kısayollar'):
        st.write('Kısa menü ile gezinip işlemlerinizi yapabilirsiniz.')

    init_db()

    if selected_page == "Genel Bakış":
        render_dashboard()
    elif selected_page == "Rezervasyonlar":
        render_bookings()
    elif selected_page == "Turlar ve Paketler":
        render_tours()
    elif selected_page == "Gelir ve Giderler":
        render_income_expense()
    elif selected_page == "Faturalar":
        render_invoices()
    elif selected_page == "Tahsilatlar":
        render_collections()
    elif selected_page == "Tedarikçi Ödemeleri":
        render_supplier_payments()
    elif selected_page == "Müşteriler ve Yolcular":
        render_customers()
    elif selected_page == "Tedarikçiler":
        render_suppliers()
    elif selected_page == "Oteller":
        render_hotels()
    elif selected_page == "Transferler":
        render_transfers()
    elif selected_page == "Rehberler":
        render_guides()
    elif selected_page == "Cari Hesaplar":
        render_accounts()
    elif selected_page == "Kasa ve Bankalar":
        render_cash_and_banks()
    elif selected_page == "Tur Kârlılığı":
        render_tour_profitability()
    elif selected_page == "Raporlar":
        render_reports()
    elif selected_page == "Drive Excel Aktarımı":
        render_drive_import()
    elif selected_page == "Belge Arşivi":
        render_documents()
    elif selected_page == "Kontrol Merkezi":
        render_control_center()
    elif selected_page == "Ayarlar":
        render_settings()


if __name__ == "__main__":
    main()
