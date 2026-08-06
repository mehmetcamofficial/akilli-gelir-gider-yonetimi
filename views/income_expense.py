import streamlit as st
from datetime import datetime
from decimal import Decimal
from database.db import engine
from sqlalchemy.orm import sessionmaker
from database.models import Transaction, Category
from services.storage_service import save_uploaded_file
from utils.ui import page_header, section_header, empty_state


def render_income_expense():
    page_header(
        "Gelir ve Giderler",
        "Muhasebe kayıtlarını hızlıca girin, belge ilişkilerini saklayın ve net kalan bakiyeleri takip edin.",
    )

    Session = sessionmaker(bind=engine)
    session = Session()

    categories = [c.name for c in session.query(Category).order_by(Category.name).all()]
    if not categories:
        categories = ["Diğer"]

    with st.form("txn_form"):
        col1, col2 = st.columns(2, gap='large')
        with col1:
            ttype = st.selectbox("İşlem Türü", ["income", "expense"], format_func=lambda x: "Gelir" if x == "income" else "Gider")
            transaction_date = st.date_input("İşlem Tarihi", value=datetime.utcnow().date())
            invoice_number = st.text_input("Fatura Numarası")
            category = st.selectbox("Kategori", categories)
            subtotal = st.number_input("KDV Hariç Tutar", min_value=0.0, value=0.0, step=1.0)
            tax = st.number_input("KDV Tutarı", min_value=0.0, value=0.0, step=1.0)
        with col2:
            party = st.text_input("Firma / Kişi")
            description = st.text_area("Açıklama")
            grand = st.number_input("Genel Toplam", min_value=0.0, value=0.0, step=1.0)
            uploaded_file = st.file_uploader("Belge Yükle (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"])
        submitted = st.form_submit_button("Kaydet")

    if submitted:
        try:
            txn = Transaction(
                transaction_type=ttype,
                transaction_date=datetime.combine(transaction_date, datetime.min.time()),
                invoice_number=invoice_number or None,
                description=description,
                party_name=party or None,
                category_id=None,
                currency="TRY",
                exchange_rate=Decimal("1.0"),
                subtotal=Decimal(str(subtotal)),
                tax_total=Decimal(str(tax)),
                discount_total=Decimal("0.00"),
                grand_total=Decimal(str(grand)),
                paid_amount=Decimal("0.00"),
                remaining_amount=Decimal(str(grand)),
                payment_status="Ödenmedi",
            )
            session.add(txn)
            session.commit()
            session.refresh(txn)

            if uploaded_file is not None:
                save_uploaded_file(uploaded_file, "income" if ttype == "income" else "expense", session, transaction_id=txn.id)

            st.success("İşlem kaydedildi.")
        except Exception as e:
            st.error(f"Kaydederken hata oluştu: {e}")

    recent = session.query(Transaction).order_by(Transaction.transaction_date.desc()).limit(15).all()
    if recent:
        section_header("Son Kayıtlar")
        st.markdown("<div class='table-container'>", unsafe_allow_html=True)
        st.markdown(
            "<table><thead><tr><th>Tarih</th><th>Tür</th><th>Firma / Kişi</th><th>Kategori</th><th>Toplam</th><th>Kalan</th><th>Durum</th></tr></thead><tbody>",
            unsafe_allow_html=True,
        )
        for txn in recent:
            st.markdown(
                f"<tr><td>{txn.transaction_date.strftime('%d.%m.%Y') if txn.transaction_date else '-'}</td>"
                f"<td>{'Gelir' if txn.transaction_type == 'income' else 'Gider'}</td>"
                f"<td>{txn.party_name or '-'}</td>"
                f"<td>{getattr(txn, 'category_id', '-') or '-'}</td>"
                f"<td>{txn.grand_total:,.2f} ₺</td>"
                f"<td>{txn.remaining_amount:,.2f} ₺</td>"
                f"<td>{txn.payment_status or '-'}</td></tr>",
                unsafe_allow_html=True,
            )
        st.markdown("</tbody></table>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        empty_state(
            "İşlem kaydı yok",
            "Muhasebe kayıtları eklenince son işlemler burada görüntülenecektir.",
        )
    session.close()
