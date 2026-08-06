import streamlit as st
from decimal import Decimal
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import CashAccount, BankAccount


def render_cash_and_banks():
    st.header("Kasa ve Bankalar")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Kasa Hesabı Ekle")
    with st.form("cash_form"):
        cash_name = st.text_input("Kasa Adı")
        cash_balance = st.number_input("Başlangıç Bakiye", min_value=0.0, value=0.0, step=0.1)
        cash_currency = st.text_input("Para Birimi", value="TRY")
        cash_submit = st.form_submit_button("Kasa Ekle")
    if cash_submit:
        if not cash_name:
            st.error("Kasa adı gerekli.")
        else:
            account = CashAccount(name=cash_name, balance=Decimal(str(cash_balance)), currency=cash_currency)
            session.add(account)
            session.commit()
            st.success("Kasa hesabı eklendi.")

    st.subheader("Banka Hesabı Ekle")
    with st.form("bank_form"):
        bank_name = st.text_input("Banka Adı")
        branch = st.text_input("Şube")
        iban = st.text_input("IBAN")
        account_number = st.text_input("Hesap No")
        bank_balance = st.number_input("Başlangıç Bakiye", min_value=0.0, value=0.0, step=0.1)
        bank_currency = st.text_input("Para Birimi", value="TRY")
        bank_submit = st.form_submit_button("Banka Ekle")
    if bank_submit:
        if not bank_name:
            st.error("Banka adı gerekli.")
        else:
            account = BankAccount(bank_name=bank_name, branch=branch, iban=iban, account_number=account_number, balance=Decimal(str(bank_balance)), currency=bank_currency)
            session.add(account)
            session.commit()
            st.success("Banka hesabı eklendi.")

    st.markdown("---")
    st.subheader("Kasa Hesapları")
    cash_accounts = session.query(CashAccount).order_by(CashAccount.name).all()
    if cash_accounts:
        for acc in cash_accounts:
            st.write(f"{acc.name} | Bakiye: {acc.balance:,.2f} {acc.currency}")
    else:
        st.info("Henüz kasa hesabı yok.")

    st.subheader("Banka Hesapları")
    bank_accounts = session.query(BankAccount).order_by(BankAccount.bank_name).all()
    if bank_accounts:
        for acc in bank_accounts:
            st.write(f"{acc.bank_name} - {acc.account_number or '-'} | Bakiye: {acc.balance:,.2f} {acc.currency}")
    else:
        st.info("Henüz banka hesabı yok.")

    session.close()
