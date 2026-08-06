from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import func, or_
from sqlalchemy.orm import sessionmaker

from database.db import database_health, engine
from database.models import (
    Booking, Collection, Customer, Document, GuideAssignment, HotelBooking,
    Passenger, Supplier, SupplierPayment, Tour, TourCostItem, Transaction,
    Transfer, Voucher,
)
from utils.ui import page_header, render_metric_cards, section_header


VALID_CURRENCIES = {"TRY", "EUR", "USD", "GBP"}


def _row(control, record, detail):
    return {"Kontrol": control, "Kayıt": record, "Detay": detail}


def _render_check_table(title, rows):
    st.markdown(f"#### {title}")
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.success("Bu grupta sorun bulunamadı.")


def _build_controls(session):
    now = datetime.now()
    upcoming_limit = now + timedelta(days=30)
    financial, operations, quality = [], [], []

    overdue_bookings = session.query(Booking).filter(
        Booking.remaining_amount > 0,
        Booking.final_payment_date.isnot(None),
        Booking.final_payment_date < now,
    ).all()
    for booking in overdue_bookings:
        financial.append(_row("Vadesi geçmiş müşteri alacağı", booking.booking_number, f"Kalan: {booking.remaining_amount} {booking.currency}"))

    overdue_payments = session.query(SupplierPayment).filter(
        SupplierPayment.remaining_amount > 0,
        SupplierPayment.due_date.isnot(None),
        SupplierPayment.due_date < now,
    ).all()
    for payment in overdue_payments:
        financial.append(_row("Vadesi geçmiş tedarikçi borcu", payment.invoice_reference or payment.id, f"Kalan: {payment.remaining_amount} {payment.currency}"))

    for booking in session.query(Booking).filter(Booking.remaining_amount > 0).all():
        financial.append(_row("Tahsilatı eksik rezervasyon", booking.booking_number, f"Eksik: {booking.remaining_amount} {booking.currency}"))
        collected = session.query(func.coalesce(func.sum(Collection.amount), 0)).filter(Collection.booking_id == booking.id).scalar() or 0
        if abs(float(collected) - float(booking.collected_total or 0)) > 0.01:
            financial.append(_row("Rezervasyon tahsilat uyuşmazlığı", booking.booking_number, f"Kayıt: {booking.collected_total}, hareket: {collected}"))

    for txn in session.query(Transaction).filter(or_(Transaction.invoice_number.is_(None), Transaction.invoice_number == "")).all():
        financial.append(_row("Faturasız gelir-gider", f"İşlem #{txn.id}", txn.description or "Açıklama yok"))
    for txn in session.query(Transaction).filter(Transaction.paid_amount > Transaction.grand_total).all():
        financial.append(_row("Fazla ödeme", f"İşlem #{txn.id}", f"Toplam {txn.grand_total}, ödenen {txn.paid_amount}"))
    duplicate_invoices = session.query(Transaction.invoice_number, func.count(Transaction.id)).filter(
        Transaction.invoice_number.isnot(None), Transaction.invoice_number != ""
    ).group_by(Transaction.invoice_number).having(func.count(Transaction.id) > 1).all()
    for number, count in duplicate_invoices:
        financial.append(_row("Mükerrer fatura numarası", number, f"{count} kayıt"))
    for txn in session.query(Transaction).filter(Transaction.currency != "TRY", or_(Transaction.exchange_rate.is_(None), Transaction.exchange_rate <= 0)).all():
        financial.append(_row("Eksik döviz kuru", f"İşlem #{txn.id}", txn.currency or "Para birimi yok"))

    upcoming = session.query(Tour).filter(Tour.is_active.is_(True), Tour.departure_datetime.between(now, upcoming_limit)).all()
    for tour in upcoming:
        bookings = session.query(Booking).filter(Booking.tour_id == tour.id).all()
        if not tour.default_guide and not session.query(GuideAssignment).filter(GuideAssignment.tour_id == tour.id).first():
            operations.append(_row("Yaklaşan turda rehber eksik", tour.code, tour.name))
        transfers = session.query(Transfer).filter(Transfer.tour_id == tour.id).all()
        if not tour.default_vehicle and not transfers:
            operations.append(_row("Transfer aracı eksik", tour.code, tour.name))
        for transfer in transfers:
            if not transfer.vehicle_plate:
                operations.append(_row("Transfer aracı eksik", tour.code, f"Transfer #{transfer.id}"))
            if not transfer.driver:
                operations.append(_row("Sürücü eksik", tour.code, f"Transfer #{transfer.id}"))
        if (tour.duration_days or 0) > 1:
            for booking in bookings:
                if not session.query(HotelBooking).filter(HotelBooking.booking_id == booking.id).first():
                    operations.append(_row("Otel onayı eksik", booking.booking_number, tour.name))
        for booking in bookings:
            if not booking.voucher_number and not session.query(Voucher).filter(Voucher.booking_id == booking.id).first():
                operations.append(_row("Voucher oluşturulmamış", booking.booking_number, tour.name))
            passenger_rows = session.query(Passenger).filter(Passenger.booking_id == booking.id).count()
            if passenger_rows < (booking.passenger_count or 0):
                operations.append(_row("Yolcu listesi eksik", booking.booking_number, f"{passenger_rows}/{booking.passenger_count}"))
        passenger_total = sum(booking.passenger_count or 0 for booking in bookings)
        if tour.capacity and passenger_total > tour.capacity:
            operations.append(_row("Kapasite aşımı", tour.code, f"{passenger_total}/{tour.capacity}"))
        costs = session.query(TourCostItem).filter(TourCostItem.tour_id == tour.id).all()
        if costs and any(item.supplier_id is None for item in costs):
            operations.append(_row("Tedarikçi atanmamış tur", tour.code, tour.name))
        revenue = sum(float(booking.grand_total or 0) for booking in bookings)
        cost = sum(float(item.amount or 0) * float(item.exchange_rate or 1) for item in costs)
        if cost > revenue:
            operations.append(_row("Maliyeti geliri aşan tur", tour.code, f"Gelir {revenue:.2f}, maliyet {cost:.2f}"))
        elif revenue and (revenue - cost) / revenue < 0.10:
            operations.append(_row("Düşük kâr marjlı tur", tour.code, f"Marj %{(revenue-cost)/revenue*100:.1f}"))

    for customer in session.query(Customer).all():
        if not customer.phone or not customer.email:
            quality.append(_row("Eksik müşteri bilgisi", f"Müşteri #{customer.id}", "Telefon veya e-posta eksik"))
        if not customer.tax_number:
            quality.append(_row("Eksik vergi numarası", f"Müşteri #{customer.id}", customer.company_name or customer.first_name))
    for supplier in session.query(Supplier).all():
        if not supplier.phone or not supplier.email:
            quality.append(_row("Eksik tedarikçi bilgisi", supplier.name, "Telefon veya e-posta eksik"))
        if not supplier.tax_number:
            quality.append(_row("Eksik vergi numarası", supplier.name, "Tedarikçi"))
    for txn in session.query(Transaction).all():
        if not txn.invoice_number:
            quality.append(_row("Eksik fatura numarası", f"İşlem #{txn.id}", txn.description or "—"))
        if txn.document_date and txn.document_date > now:
            quality.append(_row("Gelecek tarihli fatura", txn.invoice_number or txn.id, txn.document_date.strftime("%d.%m.%Y")))
        if float(txn.grand_total or 0) < 0:
            quality.append(_row("Negatif tutar", txn.invoice_number or txn.id, str(txn.grand_total)))
        if txn.currency not in VALID_CURRENCIES:
            quality.append(_row("Geçersiz para birimi", txn.invoice_number or txn.id, txn.currency or "Boş"))
    duplicate_bookings = session.query(Booking.booking_number, func.count(Booking.id)).group_by(Booking.booking_number).having(func.count(Booking.id) > 1).all()
    for number, count in duplicate_bookings:
        quality.append(_row("Mükerrer rezervasyon", number, f"{count} kayıt"))
    duplicate_files = session.query(Document.file_hash, func.count(Document.id)).filter(Document.file_hash.isnot(None)).group_by(Document.file_hash).having(func.count(Document.id) > 1).all()
    for file_hash, count in duplicate_files:
        quality.append(_row("Aynı dosya tekrar yüklenmiş", file_hash[:12], f"{count} dosya"))
    for tour in session.query(Tour).filter(Tour.return_datetime < Tour.departure_datetime).all():
        quality.append(_row("Geçersiz tarih", tour.code, "Dönüş kalkıştan önce"))

    return financial, operations, quality, overdue_bookings, overdue_payments


def render_control_center():
    page_header("Kontrol Merkezi", "Eksik kayıtları, yaklaşan işlemleri ve sistem uyarılarını tek ekrandan kontrol edin.")
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        financial, operations, quality, overdue_bookings, overdue_payments = _build_controls(session)
        all_rows = financial + operations + quality
        critical = len(overdue_bookings) + len(overdue_payments) + sum(1 for row in operations if row["Kontrol"] in {"Kapasite aşımı", "Maliyeti geliri aşan tur"})
        summary = [
            ("Kritik Uyarı", critical),
            ("Vadesi Geçmiş Tahsilat", len(overdue_bookings)),
            ("Vadesi Geçmiş Ödeme", len(overdue_payments)),
            ("Eksik Fatura", sum(1 for row in quality if row["Kontrol"] == "Eksik fatura numarası")),
            ("Eşleşmeyen Banka Hareketi", sum(1 for row in financial if "uyuşmazlığı" in row["Kontrol"])),
            ("Eksik Operasyon Bilgisi", len(operations)),
            ("Mükerrer Kayıt Şüphesi", sum(1 for row in all_rows if "Mükerrer" in row["Kontrol"] or "tekrar" in row["Kontrol"])),
            ("Düşük Kâr Marjlı Tur", sum(1 for row in operations if row["Kontrol"] == "Düşük kâr marjlı tur")),
        ]
        render_metric_cards([{"title": label, "value": value, "note": "Görüntüle"} for label, value in summary], columns=4)

        section_header("Hızlı İşlemler")
        q1, q2, q3, q4, q5, q6 = st.columns(6)
        if q1.button("Hatalı Kayıtları Aç"):
            st.session_state.control_focus = "quality"
        if q2.button("Eksik Belgeleri Göster"):
            st.session_state.control_focus = "documents"
        if q3.button("Vadesi Geçmişleri Göster"):
            st.session_state.control_focus = "overdue"
        if q4.button("Mükerrerleri Kontrol Et"):
            st.session_state.control_focus = "duplicates"
        report = pd.DataFrame(all_rows).to_csv(index=False).encode("utf-8-sig")
        q5.download_button("Veri Kalitesi Raporu İndir", report, "veri-kalitesi-raporu.csv", "text/csv")
        if q6.button("Sistem Kontrolünü Yenile"):
            st.cache_data.clear(); st.rerun()

        focus = st.session_state.get("control_focus")
        if focus:
            focused = all_rows
            if focus == "quality": focused = quality
            elif focus == "documents": focused = [row for row in all_rows if "fatura" in row["Kontrol"].lower() or "dosya" in row["Kontrol"].lower() or "voucher" in row["Kontrol"].lower()]
            elif focus == "overdue": focused = [row for row in financial if "Vadesi geçmiş" in row["Kontrol"]]
            elif focus == "duplicates": focused = [row for row in all_rows if "Mükerrer" in row["Kontrol"] or "tekrar" in row["Kontrol"]]
            _render_check_table("Seçili Kontrol Sonuçları", focused)

        financial_tab, operation_tab, quality_tab = st.tabs(["Finansal Kontroller", "Turizm Operasyon Kontrolleri", "Veri Kalitesi Kontrolleri"])
        with financial_tab: _render_check_table("Finansal Kontroller", financial)
        with operation_tab: _render_check_table("Turizm Operasyon Kontrolleri", operations)
        with quality_tab: _render_check_table("Veri Kalitesi Kontrolleri", quality)

        section_header("Sistem Özeti")
        counts = [
            ("Rezervasyon", session.query(Booking).count()), ("Finans İşlemi", session.query(Transaction).count()),
            ("Tahsilat", session.query(Collection).count()), ("Tedarikçi Ödemesi", session.query(SupplierPayment).count()),
            ("Müşteri", session.query(Customer).count()), ("Tedarikçi", session.query(Supplier).count()),
            ("Tur", session.query(Tour).count()), ("Belge", session.query(Document).count()),
        ]
        render_metric_cards([{"title": label, "value": count, "note": "Toplam kayıt"} for label, count in counts], columns=4)

        with st.expander("Teknik Sistem Bilgileri", expanded=False):
            health = database_health()
            if health["ok"]:
                st.success(health["message"])
            else:
                st.error(health["message"])
            info = {
                "Database provider": health["provider"],
                "Table count": health["table_count"] if health["table_count"] is not None else "—",
                "Last successful query": health["last_successful_query"].strftime("%d.%m.%Y %H:%M:%S UTC") if health["last_successful_query"] else "Henüz yok",
                "Application version": "1.0.0",
                "Last health check": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            }
            st.table(pd.DataFrame(info.items(), columns=["Bilgi", "Değer"]))
    finally:
        session.close()
