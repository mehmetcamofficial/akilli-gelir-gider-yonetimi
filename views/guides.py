import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Guide


def render_guides():
    st.header("Rehberler")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Yeni Rehber Ekle")
    with st.form("guide_form"):
        first_name = st.text_input("Ad")
        last_name = st.text_input("Soyad")
        phone = st.text_input("Telefon")
        email = st.text_input("E-posta")
        languages = st.text_input("Diller")
        license_number = st.text_input("Lisans No")
        specialties = st.text_area("Uzmanlıklar")
        daily_fee = st.number_input("Günlük Ücret", min_value=0.0, value=0.0, step=0.1)
        half_day_fee = st.number_input("Yarım Gün Ücret", min_value=0.0, value=0.0, step=0.1)
        currency = st.text_input("Para Birimi", value="TRY")
        iban = st.text_input("IBAN")
        notes = st.text_area("Notlar")
        submitted = st.form_submit_button("Rehber Kaydet")

    if submitted:
        if not first_name or not last_name:
            st.error("Ad ve soyad gerekli.")
        else:
            guide = Guide(
                first_name=first_name,
                last_name=last_name,
                phone=phone or None,
                email=email or None,
                languages=languages or None,
                license_number=license_number or None,
                specialties=specialties or None,
                daily_fee=daily_fee,
                half_day_fee=half_day_fee,
                currency=currency or "TRY",
                iban=iban or None,
                is_active=True,
                notes=notes or None,
            )
            session.add(guide)
            session.commit()
            st.success("Rehber kaydedildi.")

    st.markdown("---")
    st.subheader("Rehber Listesi")
    guides = session.query(Guide).order_by(Guide.first_name, Guide.last_name).limit(100).all()
    if guides:
        for g in guides:
            st.write(f"{g.id} - {g.first_name} {g.last_name} | {g.languages or '-'} | {g.phone or '-'} | Ücret: {g.daily_fee:,.2f} {g.currency}")
    else:
        st.info("Henüz rehber kaydı yok.")

    session.close()
