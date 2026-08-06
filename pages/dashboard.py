import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
import pandas as pd
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import InvoiceItem, Product, Transaction


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

    # Product profitability
    st.subheader("Ürün Bazlı Kârlılık")
    col_a, col_b = st.columns(2)
    with col_a:
        start_date = st.date_input("Başlangıç", value=datetime.utcnow().date().replace(day=1))
    with col_b:
        end_date = st.date_input("Bitiş", value=datetime.utcnow().date())

    Session = sessionmaker(bind=engine)
    session = Session()

    # join invoice items with transactions and products for sales
    items_q = session.query(InvoiceItem, Transaction, Product).join(Transaction, InvoiceItem.invoice_id==Transaction.id).outerjoin(Product, InvoiceItem.product_id==Product.id).filter(Transaction.is_deleted==False).filter(Transaction.transaction_date >= start_date).filter(Transaction.transaction_date <= end_date).filter(Transaction.invoice_type == 'sale')

    prod_map = {}
    for item, txn, prod in items_q:
        pid = item.product_id or 0
        name = prod.name if prod else item.description or 'Unknown'
        qty = Decimal(item.quantity or 0)
        revenue = Decimal(item.line_total or 0)
        avg_cost = Decimal(prod.avg_purchase_price or 0) if prod else Decimal(0)
        cost = qty * avg_cost
        if pid not in prod_map:
            prod_map[pid] = {'product': name, 'qty': Decimal(0), 'revenue': Decimal(0), 'cost': Decimal(0)}
        prod_map[pid]['qty'] += qty
        prod_map[pid]['revenue'] += revenue
        prod_map[pid]['cost'] += cost

    rows = []
    for pid, v in prod_map.items():
        profit = v['revenue'] - v['cost']
        margin = (profit / v['revenue'] * Decimal(100)) if v['revenue'] != 0 else Decimal(0)
        rows.append({'product_id': pid, 'product': v['product'], 'quantity': float(v['qty']), 'revenue': float(v['revenue']), 'cost': float(v['cost']), 'profit': float(profit), 'margin_pct': float(margin)})

    if rows:
        pdf = pd.DataFrame(rows).sort_values('profit', ascending=False)
        st.write("En kârlı ürünler")
        st.bar_chart(pdf.set_index('product')['profit'].head(10))
        st.dataframe(pdf)
        csv2 = pdf.to_csv(index=False).encode('utf-8')
        st.download_button("Ürün Kârlılık CSV İndir", data=csv2, file_name="product_profitability.csv", mime="text/csv")
        try:
            import io
            towrite2 = io.BytesIO()
            pdf.to_excel(towrite2, index=False, engine='openpyxl')
            towrite2.seek(0)
            st.download_button("Ürün Kârlılık Excel İndir", data=towrite2, file_name="product_profitability.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception:
            st.error("Excel oluşturulamadı; openpyxl yüklü olduğundan emin olun.")
    else:
        st.info("Seçilen tarihler arasında satış verisi yok veya ürün eşleşmesi bulunmuyor.")

    session.close()
