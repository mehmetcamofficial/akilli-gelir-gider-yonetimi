import streamlit as st
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func, text
from database.db import engine
import pandas as pd
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import InvoiceItem, Product, Transaction, Category
import plotly.express as px
import services.reporting_service as reporting_service


def _load_transactions():
    Session = sessionmaker(bind=engine)
    session = Session()
    rows = session.execute(text("SELECT id, transaction_type, transaction_date, grand_total FROM transactions WHERE is_deleted=0")).fetchall()
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
                logo_path = 'assets/logo_iglesias_tour_turkey.png'
                pdf_bytes = reporting_service.generate_invoice_list_pdf(sess_pdf, smin, smax, logo_path=logo_path)
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
        st.dataframe(pdf, height=300)
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
                logo_path = 'assets/logo_iglesias_tour_turkey.png'
                pdf_bytes = reporting_service.generate_product_profitability_pdf(sesspdf, start_date, end_date, logo_path=logo_path)
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
    except Exception as e:
        st.error(f'Ödeme durumu hesaplanırken hata: {e}')

    # Detailed cashflow forecast
    st.subheader('Nakit Akışı Tahmini (Gelişmiş)')
    col1, col2 = st.columns([1,2])
    with col1:
        horizon = st.selectbox('Tahmin süresi (gün)', [7, 15, 30, 60, 90], index=2)
        agg = st.selectbox('Aggregrasyon', ['Günlük', 'Haftalık', 'Aylık'])
    today = date.today()
    end_forecast = today + timedelta(days=horizon)
    try:
        qf = s.query(Transaction).filter(Transaction.is_deleted==False).filter(Transaction.due_date != None).filter(Transaction.due_date >= today).filter(Transaction.due_date <= end_forecast).all()
        if qf:
            cf_rows = []
            for t in qf:
                amt = float(t.remaining_amount or t.grand_total or 0)
                if t.transaction_type == 'income':
                    cf_rows.append({'date': t.due_date, 'flow': amt, 'direction': 'inflow'})
                else:
                    cf_rows.append({'date': t.due_date, 'flow': amt, 'direction': 'outflow'})
            df_cf = pd.DataFrame(cf_rows)
            df_cf['date'] = pd.to_datetime(df_cf['date'])
            if agg == 'Günlük':
                df_agg = df_cf.groupby(['date','direction']).agg({'flow':'sum'}).reset_index()
                df_pivot = df_agg.pivot(index='date', columns='direction', values='flow').fillna(0)
            elif agg == 'Haftalık':
                df_cf['week'] = df_cf['date'].dt.to_period('W').apply(lambda r: r.start_time)
                df_agg = df_cf.groupby(['week','direction']).agg({'flow':'sum'}).reset_index()
                df_pivot = df_agg.pivot(index='week', columns='direction', values='flow').fillna(0)
            else:
                df_cf['month'] = df_cf['date'].dt.to_period('M').apply(lambda r: r.start_time)
                df_agg = df_cf.groupby(['month','direction']).agg({'flow':'sum'}).reset_index()
                df_pivot = df_agg.pivot(index='month', columns='direction', values='flow').fillna(0)

            df_pivot['net'] = df_pivot.get('inflow', 0) - df_pivot.get('outflow', 0)
            st.area_chart(df_pivot.fillna(0))
            st.dataframe(df_pivot, height=300)
            st.download_button('Nakit Tahmini CSV İndir', data=df_pivot.reset_index().to_csv(index=False).encode('utf-8'), file_name='cashflow_forecast.csv')
        else:
            st.info('Seçilen dönem için vadesi gelen işlem bulunamadı.')
    except Exception as e:
        st.error(f'Nakit tahmini hesaplanırken hata: {e}')

    # Payment due alerts
    st.subheader('Ödeme Vadesi Uyarıları')
    try:
        days_ahead = st.number_input('Kaç gün içindeki vadeleri göster?', min_value=1, max_value=365, value=14)
        warn_date = date.today() + timedelta(days=days_ahead)
        Session3 = sessionmaker(bind=engine)
        sess3 = Session3()
        due_q = sess3.query(Transaction).filter(Transaction.is_deleted==False).filter(Transaction.due_date != None).filter(Transaction.due_date <= warn_date).filter((Transaction.payment_status != 'paid') | (Transaction.remaining_amount > 0)).order_by(Transaction.due_date).all()
        if due_q:
            due_rows = []
            for t in due_q:
                due_rows.append({'Tarih': t.due_date.strftime('%d.%m.%Y') if hasattr(t.due_date, 'strftime') else str(t.due_date), 'No': t.invoice_number or '', 'Taraf': t.party_name or '', 'Kalan': float(t.remaining_amount or 0), 'Durum': t.payment_status or ''})
            df_due = pd.DataFrame(due_rows)
            st.warning(f"{len(df_due)} adet vadesi yaklaşan/ödenmemiş işlem bulundu (son {days_ahead} gün).")
            # style: kalan>0 kırmızı, durum renkleri
            def color_kalan(v):
                try:
                    return 'color: red; font-weight: bold' if float(v) > 0 else ''
                except Exception:
                    return ''

            def color_durum(v):
                if not isinstance(v, str):
                    return ''
                low = v.lower()
                if low in ('ödenmedi', 'unpaid'):
                    return 'background-color: #fff3cd'
                if low in ('kısmen ödendi', 'partially_paid', 'partial'):
                    return 'background-color: #ffeeba'
                if low in ('ödendi', 'paid'):
                    return 'background-color: #d4edda'
                return ''

            styled = df_due.style.applymap(color_kalan, subset=['Kalan']).applymap(color_durum, subset=['Durum'])
            st.dataframe(styled, height=300)
            st.download_button('Vade Uyarıları CSV', data=df_due.to_csv(index=False).encode('utf-8'), file_name='due_alerts.csv')
            # bulk actions: select rows with checkboxes
            st.markdown('**Toplu İşlemler**')
            selected_ids = []
            selected_rows = []
            for idx, r in enumerate(due_rows):
                cols_sel = st.columns([1,6])
                with cols_sel[0]:
                    sel = st.checkbox('', key=f'due_sel_{idx}')
                with cols_sel[1]:
                    st.write(f"{r['Tarih']} | {r['No']} | {r['Taraf']} | Kalan: {r['Kalan']}")
                if sel:
                    # find transaction id by invoice number and party from DB
                    try:
                        tx = sess3.query(Transaction).filter(Transaction.invoice_number == r['No']).filter(Transaction.party_name == r['Taraf']).first()
                        if tx:
                            selected_ids.append(tx.id)
                            selected_rows.append({'id': tx.id, 'no': r['No'], 'taraf': r['Taraf'], 'tarih': r['Tarih'], 'kalan': r['Kalan']})
                    except Exception:
                        continue

            if selected_ids:
                ca, cb = st.columns(2)
                with ca:
                    if st.button('Toplu Ödemeyi İşaretle'):
                        try:
                            for tid in selected_ids:
                                txm = sess3.query(Transaction).filter(Transaction.id == int(tid)).first()
                                if txm and float(txm.remaining_amount or 0) > 0:
                                    try:
                                        paid = Decimal(str(txm.paid_amount or 0)) + Decimal(str(txm.remaining_amount or 0))
                                    except Exception:
                                        paid = Decimal(str(txm.remaining_amount or 0))
                                    txm.paid_amount = paid
                                    txm.remaining_amount = Decimal('0.00')
                                    txm.payment_status = 'ödendi'
                                    sess3.add(txm)
                            sess3.commit()
                            st.success(f"{len(selected_ids)} işlem için ödemeler işaretlendi.")
                            st.experimental_rerun()
                        except Exception as e:
                            st.error(f'Toplu ödeme işaretleme hatası: {e}')
                with cb:
                    if st.button('Toplu Hatırlatma Gönder (Simülasyon)'):
                        reminder_text_sel = "\n".join([f"Fatura: {r['no']} | {r['taraf']} | Vade: {r['tarih']} | Kalan: {r['kalan']}" for r in selected_rows])
                        st.success(f"{len(selected_rows)} hatırlatma simülasyonu oluşturuldu.")
                        st.code(reminder_text_sel)
                        st.download_button('Seçili Hatırlatma TXT İndir', data=reminder_text_sel.encode('utf-8'), file_name='selected_reminders.txt')
        else:
            st.success('Belirtilen aralıkta vadesi yaklaşan veya ödenmemiş işlem yok.')
        sess3.close()
    except Exception as e:
        st.error(f'Vade uyarıları alınırken hata: {e}')
    finally:
        s.close()
