from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from database.db import SessionLocal
from database.models import (
    AccountReconciliationLine, AccountReconciliationRun, Booking, Customer,
    CurrencySettlement, ExchangeRate, Supplier, SupplierContract,
    SupplierContractPrice, Tour, TourBudget, TourBudgetLine,
)
from services.business_value_service import (
    BusinessAuditService, CurrencyManagementService, CurrentAccountReconciliationService,
    DailyWorkCenterService, SupplierContractService, TourBudgetAnalysisService,
)
from utils.ui import empty_state, page_header


def _go(page):
    st.session_state.active_page = page
    st.rerun()


def render_daily_work_center():
    page_header("Günlük İş Merkezi", "Bugün müdahale etmeniz gereken finans ve operasyon işlerini tek ekranda tamamlayın.")
    session = SessionLocal()
    try:
        groups = DailyWorkCenterService.items(session)
        labels = {
            "collections_due": "Bugün Vadesi Gelen Tahsilatlar", "payments_due": "Bugün Vadesi Gelen Ödemeler",
            "overdue": "Vadesi Geçenler", "approvals": "Bekleyen Onaylar",
            "bank_unmatched": "Eşleşmemiş Banka Hareketleri", "critical_reconciliation": "Kritik Mutabakat Farkları",
            "missing_documents": "Eksik Tur Belgeleri", "failed_imports": "Hatalı Aktarımlar",
        }
        cols = st.columns(4)
        for index, key in enumerate(labels):
            cols[index % 4].metric(labels[key], len(groups[key]))
        for key, label in labels.items():
            rows = groups[key]
            with st.expander(f"{label} ({len(rows)})", expanded=bool(rows)):
                if not rows:
                    st.caption("Aksiyon bekleyen kayıt yok.")
                else:
                    for row in rows[:50]:
                        reference = getattr(row, "booking_number", None) or getattr(row, "invoice_reference", None) or f"Kayıt #{row.id}"
                        amount = getattr(row, "remaining_amount", None) or getattr(row, "financial_effect", None)
                        due = getattr(row, "final_payment_date", None) or getattr(row, "due_date", None) or getattr(row, "created_at", None)
                        due_text = due.strftime("%d.%m.%Y") if due else "—"
                        st.write(f"**{reference}** · {amount if amount is not None else '—'} {getattr(row, 'currency', '') or ''} · {due_text}")
                if st.button("İş Akışını Aç", key=f"work_{key}"):
                    _go(DailyWorkCenterService.ROUTES[key])
    finally:
        session.close()


def render_supplier_contracts():
    page_header("Tedarikçi Sözleşmeleri", "Hizmet tarihine göre geçerli anlaşmalı fiyatı yönetin.")
    session = SessionLocal()
    try:
        suppliers = session.query(Supplier).order_by(Supplier.name).all()
        if not suppliers:
            empty_state("Tedarikçi bulunamadı", "Önce Tedarikçiler ekranından tedarikçi ekleyin."); return
        with st.form("contract_form"):
            supplier = st.selectbox("Tedarikçi", suppliers, format_func=lambda item: item.name)
            c1, c2, c3 = st.columns(3)
            number = c1.text_input("Sözleşme Numarası")
            supplier_type = c2.selectbox("Hizmet Türü", SupplierContractService.TYPES)
            currency = c3.selectbox("Para Birimi", CurrencyManagementService.CURRENCIES)
            valid_from, valid_to = st.columns(2)
            start = valid_from.date_input("Başlangıç", value=date.today())
            end = valid_to.date_input("Bitiş", value=date.today() + timedelta(days=365))
            payment_days = st.number_input("Ödeme Vadesi (gün)", min_value=0, value=0)
            cancellation = st.text_area("İptal Kuralı")
            if st.form_submit_button("Sözleşmeyi Kaydet", type="primary"):
                if not number.strip() or end < start: st.error("Sözleşme numarası ve tarih aralığını kontrol edin.")
                else:
                    row = SupplierContract(supplier_id=supplier.id, contract_number=number.strip(), supplier_type=supplier_type, valid_from=datetime.combine(start, datetime.min.time()), valid_to=datetime.combine(end, datetime.max.time()), currency=currency, payment_terms_days=payment_days, cancellation_rule=cancellation or None)
                    session.add(row); session.flush(); BusinessAuditService.log(session, "SUPPLIER_CONTRACT_CREATED", "supplier_contract", row.id, {"supplier_id": supplier.id}); session.commit(); st.success("Sözleşme kaydedildi."); st.rerun()
        contracts = session.query(SupplierContract).order_by(SupplierContract.valid_from.desc()).all()
        if not contracts: return
        selected = st.selectbox("Fiyat eklenecek sözleşme", contracts, format_func=lambda item: f"{item.contract_number} · {session.get(Supplier, item.supplier_id).name} · {item.valid_from:%d.%m.%Y}–{item.valid_to:%d.%m.%Y}")
        with st.form("contract_price_form"):
            p1, p2, p3 = st.columns(3)
            code = p1.text_input("Hizmet Kodu"); name = p2.text_input("Hizmet Adı"); category = p3.selectbox("Gider Kategorisi", SupplierContractService.TYPES)
            p4, p5, p6 = st.columns(3)
            unit = p4.selectbox("Fiyat Birimi", ["Kişi", "Oda", "Gece", "Araç", "Gün", "Hizmet"])
            price = p5.number_input("Birim Fiyat", min_value=0.0, step=0.01); tax = p6.number_input("Vergi %", min_value=0.0, step=0.01)
            minimum = st.number_input("Asgari Miktar", min_value=0, value=0)
            if st.form_submit_button("Anlaşmalı Fiyatı Kaydet"):
                if not code.strip() or not name.strip(): st.error("Hizmet kodu ve adı zorunludur.")
                else:
                    row = SupplierContractPrice(contract_id=selected.id, service_code=code.strip(), service_name=name.strip(), expense_category=category, pricing_unit=unit, unit_price=Decimal(str(price)), tax_rate=Decimal(str(tax)), minimum_quantity=minimum)
                    session.add(row); session.flush(); BusinessAuditService.log(session, "SUPPLIER_CONTRACT_PRICE_CREATED", "supplier_contract_price", row.id); session.commit(); st.success("Fiyat kaydedildi."); st.rerun()
        prices = session.query(SupplierContractPrice).filter_by(contract_id=selected.id).all()
        st.dataframe(pd.DataFrame([{"Kod": x.service_code, "Hizmet": x.service_name, "Kategori": x.expense_category, "Birim": x.pricing_unit, "Fiyat": x.unit_price, "Vergi %": x.tax_rate} for x in prices]), hide_index=True, use_container_width=True)
        with st.expander("Hizmet tarihinde fiyat kontrolü"):
            check_date = st.date_input("Hizmet Tarihi", value=date.today()); check_code = st.text_input("Hizmet Kodu", key="contract_check_code"); quantity = st.number_input("Miktar", min_value=0.0, value=1.0)
            if st.button("Geçerli Fiyatı Bul"):
                result = SupplierContractService.price_for(session, selected.supplier_id, check_date, check_code, quantity)
                if result: st.success(f"{result['price'].service_name}: {result['total']} {result['contract'].currency} (Sözleşme: {result['contract'].contract_number})")
                else: st.warning("Bu tarih ve hizmet için geçerli sözleşme fiyatı bulunamadı.")
    finally:
        session.close()


def render_tour_budget_analysis():
    page_header("Tur Bütçesi: Planlanan / Gerçekleşen", "Tur gelirini, maliyetini, kârını ve başa baş yolcu sayısını karşılaştırın.")
    session = SessionLocal()
    try:
        tours = session.query(Tour).order_by(Tour.name).all()
        if not tours: empty_state("Tur bulunamadı", "Önce bir tur oluşturun."); return
        with st.form("budget_form"):
            tour = st.selectbox("Tur", tours, format_func=lambda item: item.name); name = st.text_input("Bütçe Adı", value=f"{date.today().year} Bütçesi")
            target = st.number_input("Hedef Yolcu", min_value=0, value=20); currency = st.selectbox("Bütçe Para Birimi", CurrencyManagementService.CURRENCIES)
            if st.form_submit_button("Bütçe Oluştur"):
                budget = TourBudget(tour_id=tour.id, name=name, passenger_target=target, currency=currency); session.add(budget); session.flush(); BusinessAuditService.log(session, "TOUR_BUDGET_CREATED", "tour_budget", budget.id); session.commit(); st.rerun()
        budgets = session.query(TourBudget).order_by(TourBudget.created_at.desc()).all()
        if not budgets: return
        budget = st.selectbox("Bütçe", budgets, format_func=lambda item: f"{session.get(Tour, item.tour_id).name} · {item.name}")
        with st.form("budget_line_form"):
            c1, c2, c3 = st.columns(3); line_type = c1.selectbox("Satır Türü", ["Gelir", "Gider"]); category = c2.text_input("Kategori"); description = c3.text_input("Açıklama")
            c4, c5, c6 = st.columns(3); quantity = c4.number_input("Miktar", min_value=0.0, value=1.0); unit_amount = c5.number_input("Birim Tutar", min_value=0.0); variable = c6.checkbox("Yolcu sayısına bağlı")
            if st.form_submit_button("Bütçe Satırı Ekle"):
                session.add(TourBudgetLine(budget_id=budget.id, line_type=line_type, category=category or "Diğer", description=description, quantity=Decimal(str(quantity)), unit_amount=Decimal(str(unit_amount)), is_variable=variable)); session.commit(); st.rerun()
        result = TourBudgetAnalysisService.calculate(session, budget)
        cols = st.columns(4); cols[0].metric("Planlanan Gelir", result["planned_revenue"]); cols[1].metric("Gerçekleşen Gelir", result["actual_revenue"]); cols[2].metric("Planlanan Maliyet", result["planned_cost"]); cols[3].metric("Gerçekleşen Maliyet", result["actual_cost"])
        cols = st.columns(3); cols[0].metric("Planlanan Kâr", result["planned_profit"]); cols[1].metric("Gerçekleşen Kâr", result["actual_profit"], result["profit_variance"]); cols[2].metric("Başa Baş Yolcu", result["break_even_passengers"] if result["break_even_passengers"] is not None else "Hesaplanamadı")
        st.dataframe(pd.DataFrame(result["categories"]), hide_index=True, use_container_width=True)
    finally: session.close()


def render_current_account_reconciliation():
    page_header("Cari Hesap Mutabakatı", "Açılış + faturalar − ödemeler − iadeler formülüyle müşteri veya tedarikçi bakiyesini doğrulayın.")
    session = SessionLocal()
    try:
        party_type = st.radio("Cari Türü", ["Tedarikçi", "Müşteri"], horizontal=True)
        parties = session.query(Supplier if party_type == "Tedarikçi" else Customer).order_by((Supplier.name if party_type == "Tedarikçi" else Customer.first_name)).all()
        if not parties: empty_state("Cari kayıt bulunamadı", "Önce müşteri veya tedarikçi oluşturun."); return
        party = st.selectbox("Cari", parties, format_func=lambda item: item.name if party_type == "Tedarikçi" else f"{item.first_name} {item.last_name or ''}")
        c1, c2, c3 = st.columns(3); start = c1.date_input("Başlangıç", value=date.today().replace(day=1)); end = c2.date_input("Bitiş", value=date.today()); currency = c3.selectbox("Para Birimi", CurrencyManagementService.CURRENCIES)
        opening = st.number_input("Açılış Bakiyesi", value=0.0, step=0.01)
        if st.button("Mutabakatı Hesapla ve Kaydet", type="primary"):
            run = CurrentAccountReconciliationService.run(session, party_type, party.id, start, end, currency, Decimal(str(opening))); st.session_state.last_account_reconciliation = run.id; st.success("Mutabakat hesaplandı ve kaydedildi.")
        run_id = st.session_state.get("last_account_reconciliation")
        run = session.get(AccountReconciliationRun, run_id) if run_id else session.query(AccountReconciliationRun).filter_by(party_type=party_type, party_id=party.id, currency=currency).order_by(AccountReconciliationRun.created_at.desc()).first()
        if run:
            cols = st.columns(5); cols[0].metric("Açılış", run.opening_balance); cols[1].metric("Faturalar", run.invoice_total); cols[2].metric("Ödemeler", run.payment_total); cols[3].metric("İade/Alacak", run.credit_total); cols[4].metric("Kapanış", run.closing_balance)
            lines = session.query(AccountReconciliationLine).filter_by(run_id=run.id).order_by(AccountReconciliationLine.entry_date).all()
            st.dataframe(pd.DataFrame([{"Tarih": x.entry_date, "Tür": x.entry_type, "Referans": x.reference, "Borç": x.debit, "Alacak": x.credit, "Bakiye": x.running_balance} for x in lines]), hide_index=True, use_container_width=True)
    finally: session.close()


def render_currency_management():
    page_header("Kur ve Kur Farkı Yönetimi", "TRY, EUR, USD ve GBP işlemlerinde gerçekleşmiş kur kazancı veya kaybını hesaplayın.")
    session = SessionLocal()
    try:
        with st.form("exchange_rate_form"):
            c1, c2, c3 = st.columns(3); rate_date = c1.date_input("Kur Tarihi", value=date.today()); currency = c2.selectbox("Döviz", ["EUR", "USD", "GBP"]); rate = c3.number_input("1 Birim Döviz / TRY", min_value=0.000001, value=1.0, format="%.6f")
            if st.form_submit_button("Kuru Kaydet"): CurrencyManagementService.save_rate(session, rate_date, currency, rate); st.success("Kur kaydedildi."); st.rerun()
        rates = session.query(ExchangeRate).order_by(ExchangeRate.rate_date.desc()).limit(100).all()
        st.dataframe(pd.DataFrame([{"Tarih": x.rate_date.date(), "Döviz": x.currency, "TRY Kuru": x.try_rate, "Kaynak": x.source} for x in rates]), hide_index=True, use_container_width=True)
        with st.form("settlement_form"):
            st.subheader("Gerçekleşmiş Kur Farkı")
            c1, c2, c3 = st.columns(3); entity_type = c1.selectbox("Kayıt Türü", ["booking", "supplier_payment", "collection"]); entity_id = c2.number_input("Kayıt ID", min_value=1, step=1); direction = c3.selectbox("İşlem Yönü", ["Tahsilat", "Ödeme"])
            c4, c5, c6 = st.columns(3); settle_currency = c4.selectbox("Para Birimi", ["EUR", "USD", "GBP"], key="settle_currency"); amount = c5.number_input("Döviz Tutarı", min_value=0.01); recognition = c6.number_input("İlk Kayıt Kuru", min_value=0.000001, value=1.0, format="%.6f")
            c7, c8 = st.columns(2); settlement = c7.number_input("Ödeme/Tahsilat Kuru", min_value=0.000001, value=1.0, format="%.6f"); settlement_date = c8.date_input("Gerçekleşme Tarihi", value=date.today())
            preview = CurrencyManagementService.realized_difference(amount, recognition, settlement, direction); st.info(f"Hesaplanan gerçekleşmiş kur farkı: {preview} TRY")
            if st.form_submit_button("Kur Farkını Kaydet", type="primary"):
                try: CurrencyManagementService.settle(session, entity_type, int(entity_id), direction, settle_currency, amount, recognition, settlement, datetime.combine(settlement_date, datetime.min.time())); st.success("Kur farkı kaydedildi."); st.rerun()
                except Exception as exc: session.rollback(); st.error(f"Kayıt oluşturulamadı: {exc}")
        rows = session.query(CurrencySettlement).order_by(CurrencySettlement.settlement_date.desc()).limit(100).all()
        st.dataframe(pd.DataFrame([{"Tarih": x.settlement_date.date(), "Kayıt": f"{x.entity_type} #{x.entity_id}", "Yön": x.direction, "Döviz": x.currency, "Tutar": x.foreign_amount, "İlk TRY": x.recognition_try, "Gerçekleşen TRY": x.settlement_try, "Kur Farkı": x.exchange_difference} for x in rows]), hide_index=True, use_container_width=True)
    finally: session.close()
