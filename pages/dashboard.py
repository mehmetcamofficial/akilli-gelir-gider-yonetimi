import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
import pandas as pd
from datetime import datetime


def _load_transactions():
    Session = sessionmaker(bind=engine)
    session = Session()
    rows = session.execute("SELECT id, transaction_type, transaction_date, grand_total FROM transactions WHERE is_deleted=0").fetchall()
    session.close()
    if not rows:
        return pd.DataFrame(columns=["id","transaction_type","transaction_date","grand_total"])
    df = pd.DataFrame(rows, columns=["id","transaction_type","transaction_date","grand_total"])
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    return df


def show():
    st.header("Genel Bakış")
    df = _load_transactions()
    if df.empty:
        st.info("Henüz işlem yok. Sol menüden Gelir & Gider ekleyebilirsiniz.")
        return

    # monthly aggregation
    df["month"] = df["transaction_date"].dt.to_period('M')
    monthly = df.groupby(["month","transaction_type"]).agg({'grand_total':'sum'}).reset_index()
    pivot = monthly.pivot(index='month', columns='transaction_type', values='grand_total').fillna(0)
    pivot.index = pivot.index.astype(str)

    st.subheader("Aylara Göre Gelir - Gider")
    st.line_chart(pivot)

    total_income = df[df.transaction_type=="income"]["grand_total"].sum()
    total_expense = df[df.transaction_type=="expense"]["grand_total"].sum()
    net = total_income - total_expense

    col1, col2, col3 = st.columns(3)
    col1.metric("Toplam Gelir", f"{total_income:,.2f} ₺")
    col2.metric("Toplam Gider", f"{total_expense:,.2f} ₺")
    col3.metric("Gelir - Gider Farkı", f"{net:,.2f} ₺")

    st.subheader("Aylık Özet Tablosu")
    st.dataframe(pivot)

    # export
    st.subheader("Rapor İndir")
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("CSV İndir", data=csv, file_name="transactions.csv", mime="text/csv")

    # Excel export
    try:
        import io
        towrite = io.BytesIO()
        df.to_excel(towrite, index=False, engine='openpyxl')
        towrite.seek(0)
        st.download_button("Excel İndir", data=towrite, file_name="transactions.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception:
        st.error("Excel oluşturulamadı; openpyxl yüklü olduğundan emin olun.")
