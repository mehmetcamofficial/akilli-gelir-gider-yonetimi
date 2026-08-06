import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Product
from decimal import Decimal


def render_products():
    st.header("Ürünler")
    Session = sessionmaker(bind=engine)
    session = Session()

    with st.form("product_form"):
        name = st.text_input("Ürün Adı")
        code = st.text_input("Kod")
        barcode = st.text_input("Barkod")
        unit = st.text_input("Birim", value="ad")
        price = st.number_input("Son Alış Fiyatı", min_value=0.0, value=0.0, step=0.01)
        stock = st.number_input("Stok", min_value=0.0, value=0.0, step=1.0)
        submit = st.form_submit_button("Ürün Ekle")

    if submit:
        if not name:
            st.error("Ürün adı gerekli")
        else:
            p = Product(name=name, code=code or None, barcode=barcode or None, unit=unit, last_purchase_price=Decimal(str(price)), avg_purchase_price=Decimal(str(price)), stock=Decimal(str(stock)))
            session.add(p)
            session.commit()
            st.success("Ürün eklendi")

    st.subheader("Ürün Listesi")
    products = session.query(Product).order_by(Product.name).all()
    for p in products:
        st.write(f"{p.id} - {p.name} | Stok: {p.stock} | Son Alış: {p.last_purchase_price} | Ortalama: {p.avg_purchase_price}")

    session.close()
