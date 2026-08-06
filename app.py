import streamlit as st
from database.db import init_db
from pages import dashboard, income_expense, invoices


def main():
    st.set_page_config(page_title="Gelir-Gider ve Akıllı Fatura Yönetim Sistemi", layout="wide")
    st.sidebar.title("Gelir-Gider ve Fatura Sistemi")
    menu = ["Genel Bakış", "Gelir & Gider", "Faturalar"]
    choice = st.sidebar.selectbox("Menü", menu)

    init_db()  # ensure DB and demo data exist on first run

    if choice == "Genel Bakış":
        dashboard.show()
    elif choice == "Gelir & Gider":
        income_expense.show()
    elif choice == "Faturalar":
        invoices.show()


if __name__ == "__main__":
    main()
