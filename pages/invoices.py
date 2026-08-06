import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Document, Transaction, InvoiceItem
from services.storage_service import save_uploaded_file
from services.validation_service import is_duplicate_invoice, validate_line_totals
from decimal import Decimal
import os


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


def show():
    st.header("Faturalar ve Belgeler")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Yeni Fatura Oluştur")
    _init_rows()
    Session = sessionmaker(bind=engine)
    session = Session()

    # prepare product list
    products = session.query(__import__('database').models.Product).order_by(__import__('database').models.Product.name).all()
    product_options = {str(p.id): f"{p.name} (Stok: {p.stock})" for p in products}

    with st.form("invoice_form"):
        inv_date = st.date_input("Fatura Tarihi")
        due_date = st.date_input("Vade Tarihi")
        invoice_number = st.text_input("Fatura Numarası")
        party = st.text_input("Firma / Müşteri / Tedarikçi")
        invoice_type = st.selectbox("Fatura Türü", ["sale", "purchase"], format_func=lambda x: "Satış" if x=="sale" else "Alış")
        currency = st.selectbox("Para Birimi", ["TRY", "EUR", "USD"], index=0)

        st.markdown("**Kalemler**")
        for i, row in enumerate(st.session_state.invoice_rows):
            cols = st.columns([3,1,1,1,1,1,1])
            with cols[0]:
                row["description"] = st.text_input(f"Açıklama {i+1}", value=row.get("description", ""), key=f"desc_{i}")
                # product selector
                prod_choice = st.selectbox(f"Ürün {i+1}", options=["-" ] + list(product_options.values()), key=f"prod_{i}")
                # map back selected product id
                selected_pid = None
                if prod_choice and prod_choice != "-":
                    # find id by matching value
                    for pid, label in product_options.items():
                        if label == prod_choice:
                            selected_pid = int(pid)
                            break
                row['product_id'] = selected_pid
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
                # compute tax amount automatically
                try:
                    base = Decimal(str(row.get('quantity',0))) * Decimal(str(row.get('unit_price',0))) - Decimal(str(row.get('discount_amount',0))) + Decimal(str(row.get('additional_cost',0)))
                    tax_amt = (base * Decimal(str(row.get('tax_rate',0)))) / Decimal('100')
                except Exception:
                    tax_amt = Decimal('0.00')
                row['tax_amount'] = float(tax_amt)
                st.write(f"KDV Tutarı: {tax_amt:.2f}")
            if st.button(f"Satırı Sil {i+1}", key=f"del_{i}"):
                remove_row(i)
                st.experimental_rerun()

        st.button("Yeni Satır Ekle", on_click=add_row)

        uploaded_file = st.file_uploader("Fatura Belgesi (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"]) 
        grand_total_input = st.number_input("Genel Toplam (Elle gir, yoksa 0)", min_value=0.0, value=0.0, step=0.01)

        submitted = st.form_submit_button("Fatura Kaydet")

    if submitted:
        try:
            # validations
            if is_duplicate_invoice(session, invoice_number, party):
                st.warning("Aynı fatura numarası bu firma için zaten kayıtlı.")

            sums = validate_line_totals(st.session_state.invoice_rows)
            if grand_total_input and abs(Decimal(str(grand_total_input)) - sums['grand_total']) > Decimal('0.5'):
                st.error(f"Elle girilmiş toplam ({grand_total_input}) ile hesaplanan toplam ({sums['grand_total']}) arasında fark var.")
            else:
                txn = Transaction(
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
                session.add(txn)
                session.commit()
                session.refresh(txn)

                # save invoice items
                for r in st.session_state.invoice_rows:
                    item = InvoiceItem(
                        invoice_id=txn.id,
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
                    # update product stock and avg cost for purchase items
                    try:
                        from services.product_service import update_purchase_price_and_stock, record_sale_and_reduce_stock
                        pid = r.get('product_id')
                        qty = Decimal(str(r.get('quantity',0)))
                        unit_price = Decimal(str(r.get('unit_price',0)))
                        if pid:
                            # infer type: income -> sale (reduce stock); expense -> purchase (increase stock)
                            if txn.transaction_type == 'income':
                                record_sale_and_reduce_stock(session, int(pid), qty, invoice_id=txn.id)
                            else:
                                update_purchase_price_and_stock(session, int(pid), qty, unit_price, invoice_id=txn.id)
                    except Exception:
                        pass
                session.commit()

                if uploaded_file is not None:
                    save_uploaded_file(uploaded_file, "income", session, transaction_id=txn.id)

                st.success("Fatura kaydedildi ve kalemler ilişkilendirildi.")
                # reset rows
                st.session_state.invoice_rows = []
                st.experimental_rerun()
        except Exception as e:
            st.error(f"Fatura kaydederken hata: {e}")

    # existing documents list
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
