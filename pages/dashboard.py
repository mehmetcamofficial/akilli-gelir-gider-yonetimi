import streamlit as st
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from database.db import engine
import pandas as pd
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import InvoiceItem, Product, Transaction, Category
import plotly.express as px
import services.reporting_service as reporting_service


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
        # PDF export for full transaction list using reporting service
        try:
            SessionLocal = sessionmaker(bind=engine)
            sess_pdf = SessionLocal()
            if not df.empty:
                smin = df.transaction_date.min().date()
                smax = df.transaction_date.max().date()
                pdf_bytes = reporting_service.generate_invoice_list_pdf(sess_pdf, smin, smax)
                st.download_button("Fatura Listesi PDF İndir", data=pdf_bytes, file_name="transactions.pdf", mime="application/pdf")
            sess_pdf.close()
        except Exception as e:
            st.error(f"PDF oluşturulamadı: {e}")
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
            # Product profitability PDF
            try:
                SessionPdf = sessionmaker(bind=engine)
                sesspdf = SessionPdf()
                pdf_bytes = reporting_service.generate_product_profitability_pdf(sesspdf, start_date, end_date)
                st.download_button("Ürün Kârlılık PDF İndir", data=pdf_bytes, file_name="product_profitability.pdf", mime="application/pdf")
                sesspdf.close()
            except Exception as e:
                st.error(f"Ürün kârlılık PDF oluşturulamadı: {e}")
        except Exception:
            st.error("Excel oluşturulamadı; openpyxl yüklü olduğundan emin olun.")
    else:
        st.info("Seçilen tarihler arasında satış verisi yok veya ürün eşleşmesi bulunmuyor.")

    session.close()

    # Advanced alerts: low margin and loss-making products
    st.subheader("Kâr Marjı Uyarıları")
    try:
        threshold_pct = st.number_input("Düşük kâr marjı eşiği (%)", min_value=0.0, max_value=100.0, value=10.0, step=0.5)
        if rows:
            lm = pdf[pdf['margin_pct'] < float(threshold_pct)].sort_values('margin_pct')
            loss = pdf[pdf['profit'] < 0].sort_values('profit')
            if not lm.empty:
                st.warning(f"Düşük kâr marjlı ürünler (<{threshold_pct}%)")
                st.dataframe(lm)
                st.download_button("Düşük Kâr CSV", data=lm.to_csv(index=False).encode('utf-8'), file_name='low_margin_products.csv')
            else:
                st.success("Düşük kâr marjlı ürün bulunmuyor.")

            if not loss.empty:
                st.error("Zarar eden ürünler")
                st.dataframe(loss)
                st.download_button("Zarar Eden CSV", data=loss.to_csv(index=False).encode('utf-8'), file_name='loss_products.csv')
            else:
                st.info("Zarar eden ürün bulunmuyor.")
        else:
            st.info("Ürün verisi olmadığından uyarı yapılamıyor.")
    except Exception as e:
        st.error(f"Uyarılar hesaplanırken hata: {e}")

    # Cashflow and category visuals
    st.subheader("Aylık Nakit Akışı")
    sess2 = sessionmaker(bind=engine)
    s = sess2()
    try:
        txs = s.query(Transaction).filter(Transaction.is_deleted==False).filter(Transaction.transaction_date >= start_date).filter(Transaction.transaction_date <= end_date).all()
        if txs:
            dfc = pd.DataFrame([{'date': t.transaction_date, 'type': t.transaction_type, 'amount': float(t.grand_total or 0)} for t in txs])
            dfc['month'] = pd.to_datetime(dfc['date']).dt.to_period('M').astype(str)
            mon = dfc.groupby(['month','type']).agg({'amount':'sum'}).reset_index()
            pivot2 = mon.pivot(index='month', columns='type', values='amount').fillna(0)
            st.plotly_chart(px.line(pivot2, labels={'index':'Ay','value':'Tutar','variable':'Tür'}), use_container_width=True)
        else:
            st.info('Seçilen dönemde kayıt yok.')
    except Exception as e:
        st.error(f'Nakit akışı oluşturulurken hata: {e}')

    st.subheader('Gider Kategorileri Dağılımı')
    try:
        # consider expenses (transaction_type == 'expense' or invoice_type == 'purchase')
        q = s.query(Transaction, Category).join(Category, Transaction.category_id==Category.id, isouter=True).filter(Transaction.is_deleted==False).filter(Transaction.transaction_date >= start_date).filter(Transaction.transaction_date <= end_date)
        data = {}
        for t, c in q:
            key = c.name if c else 'Diğer'
            if t.transaction_type == 'expense' or (t.invoice_type and t.invoice_type=='purchase'):
                data[key] = data.get(key, 0) + float(t.grand_total or 0)
        if data:
            dfcat = pd.DataFrame([{'category': k, 'amount': v} for k,v in data.items()])
            fig = px.pie(dfcat, names='category', values='amount', title='Gider Kategorileri')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info('Bu dönemde gider kaydı bulunamadı.')
    except Exception as e:
        st.error(f'Kategori grafiği oluşturulurken hata: {e}')

    st.subheader('Ödeme Durumu Dağılımı')
    try:
        q2 = s.query(Transaction.payment_status, func.count(Transaction.id)).filter(Transaction.is_deleted==False).group_by(Transaction.payment_status).all()
        if q2:
            dfps = pd.DataFrame(q2, columns=['payment_status','count'])
            fig2 = px.pie(dfps, names='payment_status', values='count', title='Ödeme Durumu Dağılımı')
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info('Ödeme durumu verisi yok.')
    except Exception as e:
        st.error(f'Ödeme durumu hesaplanırken hata: {e}')
    finally:
        s.close()
