import streamlit as st
from database.db import SessionLocal, init_db
from database.models import Notification
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
from views.document_reconciliation import render_document_reconciliation
from views.management_analytics import render_management_analytics
from views.accounting_automation import (
    render_approval_queue, render_audit_history, render_bank_reconciliation,
    render_hotel_reconciliation, render_restaurant_reconciliation,
    render_supplier_payment_reconciliation,
)
from views.ai_features import (
    render_ai_accounting_assistant, render_ai_document_review,
    render_ai_insights, render_supplier_objection,
)
from views.communications import (
    render_communication_reports, render_email_documents,
    render_notification_center, render_whatsapp_candidates,
)


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
            ("Finans", ["Gelir ve Giderler", "Faturalar", "Tahsilatlar", "Tedarikçi Ödemeleri", "Tedarikçi Ödeme Mutabakatı", "Banka Hareketleri ve Mutabakat"]),
            ("Çekirdek Operasyon", ["Müşteriler ve Yolcular", "Tedarikçiler", "Oteller", "Transferler", "Rehberler"]),
            ("Hesaplar", ["Cari Hesaplar", "Kasa ve Bankalar"]),
            ("Mutabakat", ["Belge Mutabakatı", "Restoran Mutabakatı", "Otel Mutabakatı", "Onay Bekleyen İşlemler", "İşlem Geçmişi"]),
            ("Yapay Zekâ", ["AI Belge İnceleme", "AI Muhasebe Asistanı", "AI İçgörüler", "Tedarikçi İtiraz Taslağı"]),
            ("İletişim", ["E-posta Belgeleri", "WhatsApp Rezervasyon Adayları", "Bildirim Merkezi", "İletişim Raporları"]),
            ("Rapor ve Analiz", ["Yönetim Analitiği", "Raporlar", "Excel Veri Aktarımı", "Belge Arşivi", "Kontrol Merkezi", "Ayarlar"]),
        ]
    )

    st.sidebar.markdown("---")
    with st.sidebar.expander('Yardım & Kısayollar'):
        st.write('Kısa menü ile gezinip işlemlerinizi yapabilirsiniz.')

    init_db()
    notification_session = SessionLocal()
    try:
        unread_notifications = notification_session.query(Notification).filter(Notification.is_read.is_(False), Notification.dismissed_at.is_(None)).count()
        st.sidebar.metric("🔔 Okunmamış Bildirim", unread_notifications)
    finally:
        notification_session.close()

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
    elif selected_page == "Yönetim Analitiği":
        render_management_analytics()
    elif selected_page == "Excel Veri Aktarımı":
        render_drive_import()
    elif selected_page == "Belge Arşivi":
        render_documents()
    elif selected_page == "Belge Mutabakatı":
        render_document_reconciliation()
    elif selected_page == "Restoran Mutabakatı":
        render_restaurant_reconciliation()
    elif selected_page == "Otel Mutabakatı":
        render_hotel_reconciliation()
    elif selected_page == "Tedarikçi Ödeme Mutabakatı":
        render_supplier_payment_reconciliation()
    elif selected_page == "Banka Hareketleri ve Mutabakat":
        render_bank_reconciliation()
    elif selected_page == "Onay Bekleyen İşlemler":
        render_approval_queue()
    elif selected_page == "İşlem Geçmişi":
        render_audit_history()
    elif selected_page == "AI Belge İnceleme":
        render_ai_document_review()
    elif selected_page == "AI Muhasebe Asistanı":
        render_ai_accounting_assistant()
    elif selected_page == "AI İçgörüler":
        render_ai_insights()
    elif selected_page == "Tedarikçi İtiraz Taslağı":
        render_supplier_objection()
    elif selected_page == "E-posta Belgeleri":
        render_email_documents()
    elif selected_page == "WhatsApp Rezervasyon Adayları":
        render_whatsapp_candidates()
    elif selected_page == "Bildirim Merkezi":
        render_notification_center()
    elif selected_page == "İletişim Raporları":
        render_communication_reports()
    elif selected_page == "Kontrol Merkezi":
        render_control_center()
    elif selected_page == "Ayarlar":
        render_settings()


if __name__ == "__main__":
    main()
