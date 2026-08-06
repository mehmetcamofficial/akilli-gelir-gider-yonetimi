import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Document, Transaction, InvoiceItem
from services.storage_service import save_uploaded_file
from services.validation_service import is_duplicate_invoice, validate_line_totals
from decimal import Decimal
import os
from database.models import InvoiceItem, Product
from sqlalchemy import select
from datetime import date


def _init_rows():
    if "invoice_rows" not in st.session_state:
        st.session_state.invoice_rows = [
            {"description": "", "quantity": 1, "unit": "ad", "unit_price": 0.0, "discount_amount": 0.0, "additional_cost": 0.0, "tax_amount": 0.0}
        ]


def add_row():
    st.session_state.invoice_rows.append({"description": "", "quantity": 1, "unit": "ad", "unit_price": 0.0, "discount_amount": 0.0, "additional_cost": 0.0, "tax_amount": 0.0})


def remove_row(idx: int):
    if 0 <= idx < len(st.session_state.invoice_rows):
        st.session_state.invoice_rows.pop(idx)


def render_invoices():
    st.header("Faturalar ve Belgeler")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Yeni Fatura Oluştur")
    _init_rows()
    Session = sessionmaker(bind=engine)
    session = Session()

    # prepare product list
    products = session.query(Product).order_by(Product.name).all()
    product_options = {str(p.id): f"{p.name} (Stok: {p.stock})" for p in products}

    # support editing: prefill from session_state if editing_invoice_id set
    editing_id = st.session_state.get('editing_invoice_id')
    if editing_id:
        inv_obj = session.query(Transaction).filter(Transaction.id == int(editing_id)).first()
        if inv_obj:
            st.session_state['inv_date'] = inv_obj.transaction_date.date() if hasattr(inv_obj.transaction_date, 'date') else inv_obj.transaction_date
            st.session_state['due_date'] = inv_obj.due_date.date() if inv_obj.due_date and hasattr(inv_obj.due_date, 'date') else (inv_obj.due_date or date.today())
            st.session_state['invoice_number'] = inv_obj.invoice_number
            st.session_state['party'] = inv_obj.party_name
            st.session_state['invoice_type'] = inv_obj.invoice_type or 'sale'
            st.session_state['currency'] = inv_obj.currency or 'TRY'
            # load items
            items = session.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv_obj.id).all()
            st.session_state['invoice_rows'] = []
            for it in items:
                st.session_state['invoice_rows'].append({
                    'description': it.description or '',
                    'quantity': float(it.quantity or 0),
                    'unit': it.unit or 'ad',
                    'unit_price': float(it.unit_price or 0),
                    'discount_amount': float(it.discount_amount or 0),
                    'additional_cost': float(it.additional_cost or 0),
                    'tax_amount': float(it.tax_amount or 0),
                    'tax_rate': float(it.tax_amount) and 0.0,
                    'product_id': int(it.product_id) if it.product_id else None
                })

    with st.form("invoice_form"):
        inv_date = st.date_input("Fatura Tarihi", value=st.session_state.get('inv_date', date.today()))
        due_date = st.date_input("Vade Tarihi", value=st.session_state.get('due_date', date.today()))
        invoice_number = st.text_input("Fatura Numarası", value=st.session_state.get('invoice_number',''))
        party = st.text_input("Firma / Müşteri / Tedarikçi", value=st.session_state.get('party',''))
        invoice_type = st.selectbox("Fatura Türü", ["sale", "purchase"], index=0, format_func=lambda x: "Satış" if x=="sale" else "Alış")
        currency = st.selectbox("Para Birimi", ["TRY", "EUR", "USD"], index=0)

        st.markdown("**Kalemler**")
        for i, row in enumerate(st.session_state.invoice_rows):
            cols = st.columns([3,1,1,1,1,1,1])
            with cols[0]:
                row["description"] = st.text_input(f"Açıklama {i+1}", value=row.get("description", ""), key=f"desc_{i}")
                prod_choice = st.selectbox(f"Ürün {i+1}", options=["-" ] + list(product_options.values()), key=f"prod_{i}")
                selected_pid = None
                if prod_choice and prod_choice != "-":
                    for pid, label in product_options.items():
                        if label == prod_choice:
                            selected_pid = int(pid)
                            break
                row['product_id'] = selected_pid
                if selected_pid and not row.get('tax_rate'):
                    prod = session.query(Product).filter(Product.id == int(selected_pid)).first()
                    if prod and prod.default_tax_rate is not None:
                        row['tax_rate'] = float(prod.default_tax_rate)
            with cols[1]:
                row["quantity"] = st.number_input(f"Adet {i+1}", min_value=0.0, value=float(row.get("quantity",1)), step=1.0, key=f"qty_{i}")
            with cols[2]:
                row["unit"] = st.text_input(f"Birim {i+1}", value=row.get("unit","ad"), key=f"unit_{i}")
            with cols[3]:
                row["unit_price"] = st.number_input(f"Birim Fiyat {i+1}", min_value=0.0, value=float(row.get("unit_price",0.0)), step=0.01, key=f"up_{i}")
            with cols[4]:
                row["discount_amount"] = st.number_input(f"İskonto {i+1}", min_value=0.0, value=float(row.get("discount_amount",0.0)), step=0.01, key=f"disc_{i}")
            with cols[5]:
                row["additional_cost"] = st.number_input(f"Ek Maliyet {i+1}", min_value=0.0, value=float(row.get("additional_cost",0.0)), step=0.01, key=f"addc_{i}")
            with cols[6]:
                row["tax_rate"] = st.number_input(f"KDV Oranı (%) {i+1}", min_value=0.0, value=float(row.get("tax_rate",18.0)), step=0.01, key=f"taxrate_{i}")
                try:
                    base = Decimal(str(row.get('quantity',0))) * Decimal(str(row.get('unit_price',0))) - Decimal(str(row.get('discount_amount',0))) + Decimal(str(row.get('additional_cost',0)))
                    tax_amt = (base * Decimal(str(row.get('tax_rate',0)))) / Decimal('100')
                except Exception:
                    tax_amt = Decimal('0.00')
                row['tax_amount'] = float(tax_amt)
                st.write(f"KDV Tutarı: {tax_amt:.2f}")

        uploaded_file = st.file_uploader("Fatura Belgesi (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"]) 
        grand_total_input = st.number_input("Genel Toplam (Elle gir, yoksa 0)", min_value=0.0, value=0.0, step=0.01)

        submitted = st.form_submit_button("Fatura Kaydet")

    # Row actions (outside the form to avoid using st.button inside st.form)
    st.markdown("---")
    cols_action = st.columns([1,1])
    with cols_action[0]:
        if st.button("Yeni Satır Ekle (Form dışında)", on_click=add_row):
            st.experimental_rerun()
    with cols_action[1]:
        st.write("")

    # individual delete buttons for each row
    for i in range(len(st.session_state.invoice_rows)):
        if st.button(f"Satırı Sil {i+1}", key=f"post_del_{i}"):
            remove_row(i)
            st.experimental_rerun()

    if submitted:
        try:
            if is_duplicate_invoice(session, invoice_number, party) and not editing_id:
                st.warning("Aynı fatura numarası bu firma için zaten kayıtlı.")

            sums = validate_line_totals(st.session_state.invoice_rows)
            if grand_total_input and abs(Decimal(str(grand_total_input)) - sums['grand_total']) > Decimal('0.5'):
                st.error(f"Elle girilmiş toplam ({grand_total_input}) ile hesaplanan toplam ({sums['grand_total']}) arasında fark var.")
            else:
                if editing_id:
                    txn = session.query(Transaction).filter(Transaction.id == int(editing_id)).first()
                    if not txn:
                        st.error("Düzenlenecek fatura bulunamadı.")
                    else:
                        old_items = session.query(InvoiceItem).filter(InvoiceItem.invoice_id == txn.id).all()
                        from services.product_service import adjust_stock_delta
                        for oi in old_items:
                            if oi.product_id:
                                if txn.invoice_type == 'purchase':
                                    adjust_stock_delta(session, int(oi.product_id), -Decimal(str(oi.quantity)), invoice_id=txn.id, movement_type='revert_purchase')
                                else:
                                    adjust_stock_delta(session, int(oi.product_id), Decimal(str(oi.quantity)), invoice_id=txn.id, movement_type='revert_sale')
                        session.query(InvoiceItem).filter(InvoiceItem.invoice_id == txn.id).delete()
                        session.commit()

                        txn.invoice_type = invoice_type
                        txn.transaction_date = inv_date
                        txn.document_date = inv_date
                        txn.due_date = due_date
                        txn.invoice_number = invoice_number or None
                        txn.description = f"Fatura (güncellendi): {invoice_number}"
                        txn.party_name = party or None
                        txn.currency = currency
                        txn.subtotal = sums['subtotal']
                        txn.tax_total = sums['tax_total']
                        txn.grand_total = sums['grand_total']
                        txn.remaining_amount = sums['grand_total']
                        session.add(txn)
                        session.commit()
                        session.refresh(txn)
                        new_txn = txn
                else:
                    new_txn = Transaction(
                        transaction_type="income" if sums['grand_total']>=0 else "expense",
                        invoice_type=invoice_type,
                        transaction_date=inv_date,
                        document_date=inv_date,
                        due_date=due_date,
                        invoice_number=invoice_number or None,
                        description=f"Fatura: {invoice_number}",
                        party_name=party or None,
                        currency=currency,
                        subtotal=sums['subtotal'],
                        tax_total=sums['tax_total'],
                        grand_total=sums['grand_total'],
                        paid_amount=Decimal('0.00'),
                        remaining_amount=sums['grand_total'],
                        payment_status="Ödenmedi",
                    )
                    session.add(new_txn)
                    session.commit()
                    session.refresh(new_txn)

                for r in st.session_state.invoice_rows:
                    item = InvoiceItem(
                        invoice_id=new_txn.id,
                        description=r.get('description'),
                        quantity=Decimal(str(r.get('quantity',0))),
                        unit=r.get('unit'),
                        unit_price=Decimal(str(r.get('unit_price',0))),
                        discount_amount=Decimal(str(r.get('discount_amount',0))),
                        additional_cost=Decimal(str(r.get('additional_cost',0))),
                        tax_amount=Decimal(str(r.get('tax_amount',0))),
                        line_total=(Decimal(str(r.get('quantity',0))) * Decimal(str(r.get('unit_price',0))) - Decimal(str(r.get('discount_amount',0))) + Decimal(str(r.get('additional_cost',0)))),
                        product_id=r.get('product_id')
                    )
                    session.add(item)
                    try:
                        from services.product_service import update_purchase_price_and_stock, record_sale_and_reduce_stock
                        pid = r.get('product_id')
                        qty = Decimal(str(r.get('quantity',0)))
                        unit_price = Decimal(str(r.get('unit_price',0)))
                        if pid:
                            if new_txn.invoice_type == 'sale':
                                record_sale_and_reduce_stock(session, int(pid), qty, invoice_id=new_txn.id)
                            else:
                                update_purchase_price_and_stock(session, int(pid), qty, unit_price, invoice_id=new_txn.id)
                    except Exception:
                        pass
                session.commit()

                if uploaded_file is not None:
                    save_uploaded_file(uploaded_file, "income", session, transaction_id=new_txn.id)

                if editing_id:
                    st.session_state.pop('editing_invoice_id', None)

                st.success("Fatura kaydedildi ve kalemler ilişkilendirildi.")
                st.session_state.invoice_rows = []
                st.experimental_rerun()
        except Exception as e:
            st.error(f"Fatura kaydederken hata: {e}")

    st.markdown("---")
    st.subheader("Yüklenmiş Belgeler")
    docs = session.query(Document).order_by(Document.uploaded_at.desc()).limit(100).all()
    for d in docs:
        cols = st.columns([3,1])
        with cols[0]:
            st.markdown(f"**{d.original_filename}**  ")
            st.write(f"Yüklendi: {d.uploaded_at}")
            if d.file_path and os.path.exists(d.file_path):
                ext = d.original_filename.lower()
                if ext.endswith('.pdf'):
                    try:
                        import fitz
                        doc = fitz.open(d.file_path)
                        page = doc.load_page(0)
                        pix = page.get_pixmap(matrix=fitz.Matrix(2,2))
                        img_path = d.file_path + ".preview.png"
                        pix.save(img_path)
                        st.image(img_path, width=300)
                    except Exception:
                        st.write("PDF önizlemesi oluşturulamadı.")
                else:
                    st.image(d.file_path, width=300)
        with cols[1]:
            st.download_button("İndir", data=open(d.file_path, 'rb').read(), file_name=d.original_filename)

    session.close()

    Session2 = sessionmaker(bind=engine)
    s2 = Session2()
    st.markdown("---")
    st.subheader("Fatura Listesi")
    parties = [r[0] for r in s2.query(Transaction.party_name).distinct().all() if r[0]]
    flt_party = st.selectbox("Firma filtrele", options=["Hepsi"] + parties)
    d1, d2 = st.columns(2)
    with d1:
        from_date = st.date_input("Başlangıç", value=date.today().replace(day=1))
    with d2:
        to_date = st.date_input("Bitiş", value=date.today())

    q = s2.query(Transaction).filter(Transaction.is_deleted==False)
    if flt_party and flt_party != "Hepsi":
        q = q.filter(Transaction.party_name == flt_party)
    q = q.filter(Transaction.transaction_date >= from_date)
    q = q.filter(Transaction.transaction_date <= to_date)
    rows = q.order_by(Transaction.transaction_date.desc()).limit(500).all()
    import pandas as pd
    data = []
    for r in rows:
        data.append({
            'id': r.id,
            'date': r.transaction_date,
            'party': r.party_name,
            'invoice': r.invoice_number,
            'total': float(r.grand_total or 0),
            'type': r.invoice_type or r.transaction_type
        })
    df = pd.DataFrame(data)
    st.dataframe(df)
    for r in rows:
        cols = st.columns([6,1,1,1])
        with cols[0]:
            st.write(f"{r.transaction_date.date() if hasattr(r.transaction_date,'date') else r.transaction_date} | {r.party_name} | {r.invoice_number} | {r.grand_total}")
        with cols[1]:
            if st.button("Düzenle", key=f"edit_{r.id}"):
                st.session_state['editing_invoice_id'] = r.id
                st.experimental_rerun()
        with cols[2]:
            if st.button("Sil", key=f"del_{r.id}"):
                st.session_state['delete_candidate'] = r.id
                st.session_state['delete_candidate_num'] = r.invoice_number
                st.experimental_rerun()
        with cols[3]:
            st.download_button("İndir", data=str(r.grand_total).encode('utf-8'), file_name=f"invoice_{r.id}.txt")

    if st.session_state.get('delete_candidate'):
        cid = st.session_state.get('delete_candidate')
        st.warning(f"Fatura {st.session_state.get('delete_candidate_num')} silinecek. Onaylıyor musunuz?")
        if st.button("Onayla, Sil"):
            try:
                txn_del = s2.query(Transaction).filter(Transaction.id == int(cid)).first()
                if txn_del:
                    items_del = s2.query(InvoiceItem).filter(InvoiceItem.invoice_id == txn_del.id).all()
                    from services.product_service import adjust_stock_delta
                    for oi in items_del:
                        if oi.product_id:
                            if txn_del.invoice_type == 'purchase':
                                adjust_stock_delta(s2, int(oi.product_id), -Decimal(str(oi.quantity)), invoice_id=txn_del.id, movement_type='delete_purchase')
                            else:
                                adjust_stock_delta(s2, int(oi.product_id), Decimal(str(oi.quantity)), invoice_id=txn_del.id, movement_type='delete_sale')
                    txn_del.is_deleted = True
                    s2.add(txn_del)
                    s2.commit()
                    st.success('Fatura silindi (yumuşak silme). Stok düzeltildi.')
                else:
                    st.error('Silinecek fatura bulunamadı.')
            except Exception as e:
                st.error(f'Silme sırasında hata: {e}')
            finally:
                st.session_state.pop('delete_candidate', None)
                st.session_state.pop('delete_candidate_num', None)
                st.experimental_rerun()
        if st.button("İptal"):
            st.session_state.pop('delete_candidate', None)
            st.session_state.pop('delete_candidate_num', None)
            st.experimental_rerun()
    if not df.empty:
        st.download_button("Fatura CSV İndir", data=df.to_csv(index=False).encode('utf-8'), file_name='invoices.csv')
        try:
            import io
            towrite = io.BytesIO()
            df.to_excel(towrite, index=False, engine='openpyxl')
            towrite.seek(0)
            st.download_button("Fatura Excel İndir", data=towrite, file_name='invoices.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        except Exception:
            st.error('Excel oluşturulamadı; openpyxl yüklü olmalı.')
    s2.close()
