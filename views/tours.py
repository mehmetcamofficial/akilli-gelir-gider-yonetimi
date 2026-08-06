from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from database.db import engine
from database.models import Booking, Tour, TourCostItem, TourDeparture
from utils.ui import empty_state, format_currency, page_header, render_metric_cards, section_header


TOUR_TYPES = ["Günlük Tur", "Paket Tur", "Kültür Turu", "Doğa Turu", "Şehir Turu", "Özel Tur", "Diğer"]
TOUR_STATUSES = ["Taslak", "Satışta", "Kesinleşti", "Tamamlandı", "İptal"]
CURRENCIES = ["TRY", "EUR", "USD", "GBP"]


def _combine(day, clock):
    return datetime.combine(day, clock)


def _tour_totals(session, tour):
    revenue, reservations, passengers = session.query(
        func.coalesce(func.sum(Booking.grand_total), 0),
        func.count(Booking.id),
        func.coalesce(func.sum(Booking.passenger_count), 0),
    ).filter(Booking.tour_id == tour.id).one()
    cost = session.query(func.coalesce(func.sum(TourCostItem.amount * TourCostItem.exchange_rate), 0)).filter(
        TourCostItem.tour_id == tour.id
    ).scalar() or 0
    return Decimal(revenue or 0), Decimal(cost or 0), int(reservations or 0), int(passengers or 0)


def _render_tour_form(session, tour=None):
    is_edit = tour is not None
    st.subheader("Turu veya Paketi Düzenle" if is_edit else "Yeni Tur veya Paket")
    start_value = (tour.departure_datetime or datetime.now()) if tour else datetime.now() + timedelta(days=7)
    end_value = (tour.return_datetime or start_value + timedelta(hours=8)) if tour else start_value + timedelta(hours=8)
    with st.form("tour_form", clear_on_submit=not is_edit):
        first, second, third = st.columns(3)
        code = first.text_input("Tur kodu *", value=tour.code if tour else "")
        name = second.text_input("Tur adı *", value=tour.name if tour else "")
        current_type = tour.tour_type if tour and tour.tour_type in TOUR_TYPES else TOUR_TYPES[0]
        tour_type = third.selectbox("Tur türü *", TOUR_TYPES, index=TOUR_TYPES.index(current_type))

        first, second = st.columns(2)
        start_location = first.text_input("Başlangıç noktası *", value=tour.start_location if tour else "")
        end_location = second.text_input("Bitiş noktası *", value=tour.end_location if tour else "")

        d1, d2, t1, t2 = st.columns(4)
        start_date = d1.date_input("Başlangıç tarihi *", value=start_value.date())
        end_date = d2.date_input("Bitiş tarihi *", value=end_value.date())
        departure_time = t1.time_input("Kalkış saati *", value=start_value.time().replace(second=0, microsecond=0))
        return_time = t2.time_input("Dönüş saati *", value=end_value.time().replace(second=0, microsecond=0))

        c1, c2, c3 = st.columns(3)
        capacity = c1.number_input("Kapasite *", min_value=1, step=1, value=int(tour.capacity or 1) if tour else 20)
        minimum = c2.number_input("Minimum katılımcı *", min_value=1, step=1, value=int(tour.min_participants or 1) if tour else 5)
        currency = c3.selectbox("Para birimi *", CURRENCIES, index=CURRENCIES.index(tour.currency) if tour and tour.currency in CURRENCIES else 0)

        p1, p2, p3 = st.columns(3)
        adult_price = p1.number_input("Yetişkin fiyatı *", min_value=0.0, step=100.0, value=float(tour.adult_price or 0) if tour else 0.0)
        child_price = p2.number_input("Çocuk fiyatı *", min_value=0.0, step=100.0, value=float(tour.child_price or 0) if tour else 0.0)
        infant_price = p3.number_input("Bebek fiyatı *", min_value=0.0, step=100.0, value=float(tour.infant_price or 0) if tour else 0.0)

        included = st.text_area("Dahil hizmetler", value=tour.included_services or "" if tour else "")
        excluded = st.text_area("Hariç hizmetler", value=tour.excluded_services or "" if tour else "")
        cancellation = st.text_area("İptal koşulları", value=tour.cancellation_policy or "" if tour else "")
        status_index = TOUR_STATUSES.index(tour.status) if tour and tour.status in TOUR_STATUSES else 0
        status = st.selectbox("Durum *", TOUR_STATUSES, index=status_index)
        notes = st.text_area("Notlar", value=tour.notes or "" if tour else "")
        active = st.checkbox("Aktif", value=tour.is_active if tour else True)

        save, cancel = st.columns(2)
        submitted = save.form_submit_button("Değişiklikleri Kaydet" if is_edit else "Turu Kaydet", type="primary")
        cancelled = cancel.form_submit_button("Vazgeç")

    if cancelled:
        st.session_state.tour_form_open = False
        st.session_state.pop("tour_edit_id", None)
        st.rerun()
    if not submitted:
        return
    required = [code.strip(), name.strip(), start_location.strip(), end_location.strip()]
    if not all(required):
        st.error("Yıldızlı alanların tamamını doldurun.")
        return
    if minimum > capacity:
        st.error("Minimum katılımcı kapasiteden büyük olamaz.")
        return
    departure = _combine(start_date, departure_time)
    returning = _combine(end_date, return_time)
    if returning <= departure:
        st.error("Bitiş tarihi ve saati başlangıçtan sonra olmalıdır.")
        return
    duplicate = session.query(Tour).filter(Tour.code == code.strip())
    if is_edit:
        duplicate = duplicate.filter(Tour.id != tour.id)
    if duplicate.first():
        st.error("Bu tur kodu zaten kullanılıyor.")
        return

    target = tour or Tour()
    target.code = code.strip()
    target.name = name.strip()
    target.tour_type = tour_type
    target.start_location = start_location.strip()
    target.end_location = end_location.strip()
    target.departure_datetime = departure
    target.return_datetime = returning
    target.duration_days = max(1, (returning.date() - departure.date()).days + 1)
    target.capacity = capacity
    target.min_participants = minimum
    target.adult_price = Decimal(str(adult_price))
    target.child_price = Decimal(str(child_price))
    target.infant_price = Decimal(str(infant_price))
    target.currency = currency
    target.included_services = included
    target.excluded_services = excluded
    target.cancellation_policy = cancellation
    target.status = status
    target.notes = notes
    target.is_active = active
    target.updated_at = datetime.utcnow()
    if not is_edit:
        session.add(target)
    session.commit()
    st.session_state.tour_form_open = False
    st.session_state.pop("tour_edit_id", None)
    st.success("Tur bilgileri kaydedildi.")
    st.rerun()


def render_tours():
    page_header("Turlar ve Paketler", "Tur, paket, kalkış, kapasite, fiyat ve maliyet bilgilerini yönetin.")
    if st.button("+ Yeni Tur veya Paket", type="primary"):
        st.session_state.tour_form_open = True
        st.session_state.pop("tour_edit_id", None)

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        edit_id = st.session_state.get("tour_edit_id")
        edit_tour = session.get(Tour, edit_id) if edit_id else None
        if st.session_state.get("tour_form_open"):
            _render_tour_form(session, edit_tour)
            st.markdown("---")

        tours = session.query(Tour).order_by(Tour.departure_datetime.desc()).all()
        totals = {tour.id: _tour_totals(session, tour) for tour in tours}
        now = datetime.now()
        active_tours = [tour for tour in tours if tour.is_active]
        upcoming = [tour for tour in active_tours if tour.departure_datetime and tour.departure_datetime >= now]
        all_bookings = sum(value[2] for value in totals.values())
        capacity = sum(tour.capacity or 0 for tour in active_tours)
        passengers = sum(totals[tour.id][3] for tour in active_tours)
        month_tours = [tour for tour in tours if tour.departure_datetime and tour.departure_datetime.year == now.year and tour.departure_datetime.month == now.month]
        month_revenue = sum((totals[tour.id][0] for tour in month_tours), Decimal("0"))
        month_profit = sum((totals[tour.id][0] - totals[tour.id][1] for tour in month_tours), Decimal("0"))
        render_metric_cards([
            {"title": "Aktif Tur", "value": len(active_tours), "note": "Satışa açık kayıt"},
            {"title": "Yaklaşan Kalkış", "value": len(upcoming), "note": "Bugünden sonraki kalkış"},
            {"title": "Toplam Rezervasyon", "value": all_bookings, "note": "Turlara bağlı kayıt"},
            {"title": "Ortalama Doluluk", "value": f"%{(passengers / capacity * 100 if capacity else 0):.1f}", "note": "Aktif tur kapasitesi"},
            {"title": "Bu Ay Tur Geliri", "value": format_currency(month_revenue), "note": "Bu ay kalkacak turlar"},
            {"title": "Bu Ay Tur Kârı", "value": format_currency(month_profit), "note": "Gelir eksi tahmini maliyet"},
        ], columns=3)

        section_header("Filtreler")
        f1, f2, f3, f4 = st.columns(4)
        search = f1.text_input("Arama").strip().lower()
        date_range = f2.date_input(
            "Tarih aralığı",
            value=(date.today() - timedelta(days=3650), date.today() + timedelta(days=3650)),
        )
        type_filter = f3.multiselect("Tur türü", sorted({tour.tour_type for tour in tours if tour.tour_type}))
        status_filter = f4.multiselect("Durum", TOUR_STATUSES)
        f1, f2, f3, f4 = st.columns(4)
        departure_filter = f1.multiselect("Kalkış noktası", sorted({tour.start_location for tour in tours if tour.start_location}))
        active_filter = f2.selectbox("Aktif / Pasif", ["Tümü", "Aktif", "Pasif"])
        low_occupancy = f3.checkbox("Düşük doluluk")
        losing = f4.checkbox("Zarar eden")

        filtered = []
        start_filter, end_filter = date_range if isinstance(date_range, (tuple, list)) and len(date_range) == 2 else (date.min, date.max)
        for tour in tours:
            revenue, cost, reservations, passenger_count = totals[tour.id]
            occupancy = passenger_count / tour.capacity * 100 if tour.capacity else 0
            haystack = f"{tour.code} {tour.name}".lower()
            departure_day = tour.departure_datetime.date() if tour.departure_datetime else None
            if search and search not in haystack:
                continue
            if departure_day and not (start_filter <= departure_day <= end_filter):
                continue
            if type_filter and tour.tour_type not in type_filter:
                continue
            if status_filter and tour.status not in status_filter:
                continue
            if departure_filter and tour.start_location not in departure_filter:
                continue
            if active_filter == "Aktif" and not tour.is_active or active_filter == "Pasif" and tour.is_active:
                continue
            if low_occupancy and occupancy >= 50:
                continue
            if losing and revenue >= cost:
                continue
            filtered.append(tour)

        section_header("Tur Listesi", "Kapasite, rezervasyon ve kârlılık durumunu birlikte izleyin.")
        if not tours:
            empty_state("Henüz tur veya paket oluşturulmamış.", "İlk turunuzu oluşturarak kapasite, rezervasyon, gelir ve maliyet takibine başlayın.")
            if st.button("+ İlk Turu Oluştur"):
                st.session_state.tour_form_open = True
                st.rerun()
            return
        rows = []
        for tour in filtered:
            revenue, cost, reservations, passenger_count = totals[tour.id]
            occupancy = passenger_count / tour.capacity * 100 if tour.capacity else 0
            rows.append({
                "Tur Kodu": tour.code, "Tur Adı": tour.name, "Tur Türü": tour.tour_type or "—",
                "Kalkış Tarihi": tour.departure_datetime.strftime("%d.%m.%Y %H:%M") if tour.departure_datetime else "—",
                "Süre": f"{tour.duration_days or 0} gün", "Kapasite": tour.capacity or 0,
                "Rezervasyon": reservations, "Doluluk %": round(occupancy, 1),
                "Satış Geliri": format_currency(revenue, tour.currency), "Tahmini Maliyet": format_currency(cost, tour.currency),
                "Tahmini Kâr": format_currency(revenue - cost, tour.currency), "Durum": tour.status or "Taslak",
                "İşlemler": "Seçili tur menüsü",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        if not filtered:
            st.info("Filtrelere uygun tur bulunamadı.")
            return
        selected_id = st.selectbox("İşlem yapılacak tur", [tour.id for tour in filtered], format_func=lambda tour_id: next(f"{t.code} — {t.name}" for t in filtered if t.id == tour_id))
        selected = session.get(Tour, selected_id)
        a1, a2, a3, a4, a5, a6, a7 = st.columns(7)
        if a1.button("Görüntüle"):
            st.session_state.tour_detail_id = selected.id
        if a2.button("Düzenle"):
            st.session_state.tour_edit_id = selected.id
            st.session_state.tour_form_open = True
            st.rerun()
        if a3.button("Maliyetleri Aç"):
            st.session_state.tour_cost_id = selected.id
        if a4.button("Rezervasyonları Gör"):
            st.session_state.tour_booking_id = selected.id
        if a5.button("Kopyala"):
            copy = Tour(code=f"{selected.code}-KOPYA-{datetime.now():%H%M%S}", name=f"{selected.name} (Kopya)", tour_type=selected.tour_type, start_location=selected.start_location, end_location=selected.end_location, duration_days=selected.duration_days, departure_datetime=selected.departure_datetime, return_datetime=selected.return_datetime, capacity=selected.capacity, min_participants=selected.min_participants, adult_price=selected.adult_price, child_price=selected.child_price, infant_price=selected.infant_price, currency=selected.currency, included_services=selected.included_services, excluded_services=selected.excluded_services, cancellation_policy=selected.cancellation_policy, notes=selected.notes, status="Taslak", is_active=False)
            session.add(copy); session.commit(); st.success("Tur taslak olarak kopyalandı."); st.rerun()
        if a6.button("Pasife Al" if selected.is_active else "Aktife Al"):
            selected.is_active = not selected.is_active; selected.updated_at = datetime.utcnow(); session.commit(); st.rerun()
        if a7.button("Sil"):
            if session.query(Booking).filter(Booking.tour_id == selected.id).count():
                st.error("Rezervasyonu bulunan tur silinemez; önce pasife alın.")
            else:
                session.query(TourCostItem).filter(TourCostItem.tour_id == selected.id).delete()
                session.query(TourDeparture).filter(TourDeparture.tour_id == selected.id).delete()
                session.delete(selected); session.commit(); st.success("Tur silindi."); st.rerun()

        if st.session_state.get("tour_detail_id") == selected.id:
            st.info(f"{selected.name} • {selected.start_location} → {selected.end_location} • {selected.capacity} kişi • {selected.status}")
        if st.session_state.get("tour_cost_id") == selected.id:
            costs = session.query(TourCostItem).filter(TourCostItem.tour_id == selected.id).all()
            st.dataframe(pd.DataFrame([{"Maliyet Türü": c.cost_type, "Açıklama": c.description, "Tutar": float(c.amount or 0), "Para Birimi": c.currency} for c in costs]), hide_index=True)
        if st.session_state.get("tour_booking_id") == selected.id:
            bookings = session.query(Booking).filter(Booking.tour_id == selected.id).all()
            st.dataframe(pd.DataFrame([{"Rezervasyon": b.booking_number, "Yolcu": b.passenger_count, "Toplam": float(b.grand_total or 0), "Durum": b.booking_status} for b in bookings]), hide_index=True)
    finally:
        session.close()
