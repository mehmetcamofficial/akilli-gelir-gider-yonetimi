import streamlit as st
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
import pandas as pd
from database.db import engine
from database.models import Tour, Booking
from utils.ui import page_header, section_header, format_currency, empty_state


def render_tour_profitability():
    page_header(
        "Tur Kârlılığı",
        "Tur bazında gelir ve kapasite verilerini görselleştirerek kârlılığı net şekilde analiz edin.",
    )
    Session = sessionmaker(bind=engine)
    session = Session()

    tours = session.query(Tour).order_by(Tour.name).all()
    if not tours:
        empty_state(
            "Tur kaydı yok",
            "Tur ve rezervasyon verisi girildikçe kârlılık raporları dolacaktır.",
        )
        session.close()
        return

    tour_rows = []
    for tour in tours:
        revenue = session.query(func.coalesce(func.sum(Booking.grand_total), 0)).filter(Booking.tour_id == tour.id).scalar() or 0
        passengers = session.query(func.coalesce(func.sum(Booking.passenger_count), 0)).filter(Booking.tour_id == tour.id).scalar() or 0
        occupancy = (passengers / tour.capacity * 100) if tour.capacity else 0
        tour_rows.append({
            "Tur": tour.name,
            "Gelir": float(revenue),
            "Yolcu": int(passengers),
            "Kapasite": tour.capacity or 0,
            "Doluluk %": round(occupancy, 1),
        })

    df = pd.DataFrame(tour_rows).sort_values("Gelir", ascending=False)
    section_header("Tur Kârlılık Tablosu")
    st.dataframe(df)

    if not df.empty:
        col1, col2 = st.columns(2, gap='large')
        with col1:
            st.bar_chart(df.set_index("Tur")["Gelir"])
        with col2:
            st.bar_chart(df.set_index("Tur")["Doluluk %"])
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Tur Kârlılık CSV İndir", data=csv, file_name="tour_profitability.csv", mime="text/csv")

    session.close()
