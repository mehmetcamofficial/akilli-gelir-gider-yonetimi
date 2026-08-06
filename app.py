import streamlit as st
from database.db import init_db
from pages import dashboard, income_expense, invoices


def main():
    st.set_page_config(page_title="Gelir-Gider ve Akıllı Fatura Yönetim Sistemi", layout="wide")
    st.sidebar.title("🧾 Gelir-Gider & Fatura")
    menu = ["🏠 Genel Bakış", "➕ Gelir & Gider", "📄 Faturalar", "📦 Ürünler"]
    choice = st.sidebar.selectbox("Gezinti", menu)
    st.sidebar.markdown("---")
    with st.sidebar.expander('Yardım & Kısayollar'):
        st.write('- `Genel Bakış`: Dashboard ve raporlar')
        st.write('- `Gelir & Gider`: Hızlı işlem ekleme')
        st.write('- `Faturalar`: Fatura oluşturma ve yönetim')
        st.write('- `Ürünler`: Ürün ve stok yönetimi')
        st.write('Kişiselleştirme için `assets/logo_iglesias_tour_turkey.png` yükleyin.')
    st.sidebar.markdown("\n")

    init_db()  # ensure DB and demo data exist on first run

    if choice == "Genel Bakış":
        dashboard.show()
    elif choice == "Gelir & Gider":
        income_expense.show()
    elif choice == "Faturalar":
        invoices.show()
    elif choice == "Ürünler":
        from pages import products
        products.show()


if __name__ == "__main__":
    main()
