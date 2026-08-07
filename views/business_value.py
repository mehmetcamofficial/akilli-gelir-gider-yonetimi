from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from database.db import SessionLocal
from database.models import (
    AccountReconciliationLine, AccountReconciliationRun, Booking, Customer,
    CurrencySettlement, ExchangeRate, Supplier, SupplierContract,
    SupplierContractPrice, Tour, TourBudget, TourBudgetLine, ContractVersion,
    ContractPriceRule, RestaurantPriceRule, HotelPriceRule, TransferPriceRule,
    GuidePriceRule, ContractPriceHistory, ContractDocument,
)
from services.business_value_service import (
    BusinessAuditService, CurrencyManagementService, CurrentAccountReconciliationService,
    DailyWorkCenterService, SupplierContractService, TourBudgetAnalysisService,
    ContractPriceService, ContractManagementService,
)
from services.storage_service import load_document_bytes
from services.current_account_service import (
    AccountAnalyticsService, AutomaticAccountReconciliationService,
    CurrentAccountProjectionService, DailyCurrentAccountService,
    OpenItemMatchingService,
)
from database.models import (
    CurrentAccount, CurrentAccountMovement, OpenItem, AccountReconciliation,
    AccountReconciliationDifference, AccountRiskScore,
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
            "expiring_contracts": "Süresi Yaklaşan Sözleşmeler",
            "account_receivables_due":"Bugün Vadesi Gelen Alacak","account_payables_due":"Bugün Vadesi Gelen Borç",
            "overdue_customers":"Vadesi Geçen Müşteri","overdue_suppliers":"Vadesi Geçen Tedarikçi",
            "unmatched_payments":"Eşleşmeyen Ödeme","pending_account_reconciliations":"Mutabakat Bekleyen Cari",
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


def render_contract_prices():
    page_header("Sözleşme ve Fiyatlar", "Tedarikçi, otel, restoran, transfer ve rehberlerle yapılan fiyat anlaşmalarını yönetin ve faturaları geçerli sözleşmeye göre kontrol edin.")
    session = SessionLocal()
    try:
        ContractManagementService.create_expiry_notifications(session)
        now = datetime.utcnow(); contracts = session.query(SupplierContract).all(); rules = session.query(ContractPriceRule).filter(ContractPriceRule.active.is_(True)).all()
        for contract in contracts: contract.status = ContractPriceService.contract_status(contract, now)
        session.commit()
        active = [x for x in contracts if x.status == "Aktif"]; expiring = [x for x in contracts if x.status == "Süresi Yaklaşıyor" and (x.valid_until or x.valid_to) <= now + timedelta(days=30)]; expired = [x for x in contracts if x.status == "Süresi Doldu"]
        supplier_ids_with_price = {session.get(SupplierContract, session.get(ContractVersion, rule.version_id).contract_id).supplier_id for rule in rules}; missing = session.query(Supplier).filter(~Supplier.id.in_(supplier_ids_with_price)).count() if supplier_ids_with_price else session.query(Supplier).count()
        recent_increases = session.query(ContractPriceHistory).filter(ContractPriceHistory.created_at >= now - timedelta(days=30), ContractPriceHistory.change_percentage > 0).count()
        cards = st.columns(5); cards[0].metric("Aktif Sözleşme", len(active)); cards[1].metric("30 Gün İçinde Bitecek", len(expiring)); cards[2].metric("Süresi Dolmuş", len(expired)); cards[3].metric("Fiyatı Eksik Tedarikçi", missing); cards[4].metric("Son 30 Gün Fiyat Artışı", recent_increases)
        tabs = st.tabs(["Aktif Sözleşmeler", "Fiyat Listeleri", "Süresi Yaklaşanlar", "Fiyat Geçmişi", "Maliyet Simülasyonu", "Excel Aktarımı"])
        suppliers = session.query(Supplier).order_by(Supplier.name).all(); tours = session.query(Tour).order_by(Tour.name).all()
        with tabs[0]:
            if not suppliers: empty_state("Tedarikçi bulunamadı", "Önce bir tedarikçi oluşturun.")
            else:
                with st.expander("Yeni Sözleşme", expanded=not contracts):
                    with st.form("complete_contract_form"):
                        supplier = st.selectbox("1. Tedarikçi", suppliers, format_func=lambda x: x.name); contract_type = st.selectbox("2. Sözleşme Türü", ContractPriceService.CONTRACT_TYPES)
                        c1,c2,c3=st.columns(3); start=c1.date_input("3. Başlangıç",date.today()); end=c2.date_input("Bitiş",date.today()+timedelta(days=365)); currency=c3.selectbox("4. Para Birimi",CurrencyManagementService.CURRENCIES)
                        title=st.text_input("Sözleşme Başlığı"); number=st.text_input("Sözleşme Numarası"); pricing_model=st.selectbox("5. Fiyat Modeli",["Kişi Başı","Oda / Gece","Kişi / Gece","Sabit Grup","Tek Yön","Gidiş-Dönüş","Yarım Gün","Tam Gün"])
                        service_name=st.text_input("Hizmet / Menü / Rota Adı"); tour=st.selectbox("Tur (isteğe bağlı)",[None]+tours,format_func=lambda x:"Tüm turlar" if x is None else x.name); destination=st.text_input("Destinasyon (isteğe bağlı)")
                        base=st.number_input("Sabit / Temel Fiyat",min_value=0.0); adult=child=infant=0.0; subtype={}
                        if contract_type=="Restoran":
                            r1,r2,r3=st.columns(3); subtype["meal_type"]=r1.text_input("Öğün Türü"); subtype["menu_name"]=r2.text_input("Menü Adı"); adult=r3.number_input("Yetişkin Fiyatı",min_value=0.0); child=st.number_input("Çocuk Fiyatı",min_value=0.0); infant=st.number_input("Bebek Fiyatı",min_value=0.0); subtype["free_guide"]=st.checkbox("Rehber ücretsiz"); subtype["free_driver"]=st.checkbox("Şoför ücretsiz"); subtype["free_person_ratio"]=st.number_input("Kaç ödeyen kişiye 1 ücretsiz?",min_value=0,value=0); subtype["guide_price"]=0; subtype["driver_price"]=0; subtype["additional_service_price"]=0; subtype["minimum_passenger_count"]=0; subtype["group_price"]=base
                        elif contract_type=="Otel":
                            subtype["room_type"]=st.text_input("Oda Türü",value="double"); subtype["board_type"]=st.selectbox("Pansiyon",["RO","BB","HB","FB","AI"]); subtype["single_room"]=st.number_input("Tek Kişilik Oda",min_value=0.0); subtype["double_room"]=st.number_input("Çift Kişilik Oda",min_value=0.0); subtype["triple_room"]=st.number_input("Üç Kişilik Oda",min_value=0.0); subtype["family_room"]=0; subtype["city_tax"]=st.number_input("Şehir Vergisi",min_value=0.0)
                        elif contract_type=="Transfer":
                            subtype["origin"]=st.text_input("Başlangıç"); subtype["destination"]=st.text_input("Varış"); subtype["vehicle_type"]=st.selectbox("Araç",["Sedan","Minivan","Minibus","Midibus","Bus","VIP","Other"]); subtype["passenger_capacity"]=st.number_input("Kapasite",min_value=1,value=4); subtype["one_way_price"]=st.number_input("Tek Yön",min_value=0.0); subtype["round_trip_price"]=st.number_input("Gidiş-Dönüş",min_value=0.0); subtype["waiting_hour_price"]=0; subtype["extra_kilometer_price"]=0; subtype["airport_fee"]=0; subtype["night_surcharge"]=0; subtype["driver_accommodation"]=0
                        elif contract_type=="Rehber":
                            subtype["language"]=st.text_input("Dil"); subtype["service_type"]=st.selectbox("Hizmet Süresi",["Yarım Gün","Tam Gün"]); subtype["half_day_price"]=st.number_input("Yarım Gün",min_value=0.0); subtype["full_day_price"]=st.number_input("Tam Gün",min_value=0.0); subtype["hourly_overtime"]=st.number_input("Fazla Saat",min_value=0.0); subtype["overnight_allowance"]=0; subtype["meal_allowance"]=0; subtype["transportation_allowance"]=0; subtype["museum_fee"]=0
                        tax_included=st.checkbox("Vergi fiyata dahil"); tax_rate=st.number_input("Vergi %",min_value=0.0); document=st.file_uploader("7. Sözleşme Belgesi",type=["pdf","jpg","jpeg","png","xlsx","xls"]); preview=st.checkbox("8. Bilgileri kontrol ettim")
                        save=st.form_submit_button("9. Kaydet",type="primary",disabled=not preview)
                    if save:
                        try:
                            if end<start or not title or not service_name: raise ValueError("Başlık, hizmet ve geçerli tarih aralığı zorunludur.")
                            start_dt=datetime.combine(start,datetime.min.time()); end_dt=datetime.combine(end,datetime.max.time()); contract,version=ContractManagementService.create_contract(session,supplier.id,contract_type,title,start_dt,end_dt,currency,contract_number=number,tax_included=tax_included,tax_rate=tax_rate)
                            ContractManagementService.create_price_rule(session,contract,version,contract_type,service_name,start_dt,end_dt,pricing_model,subtype_values=subtype,tour_id=tour.id if tour else None,destination=destination or None,currency=currency,base_price=base,adult_price=adult,child_price=child,infant_price=infant,tax_rate=tax_rate,tax_included=tax_included)
                            if document: ContractManagementService.store_document(session,contract,version,document.getvalue(),document.name,document.type)
                            session.commit(); st.success("Sözleşme, fiyat kuralı ve belge geçmişi kaydedildi."); st.rerun()
                        except Exception as exc: session.rollback(); st.error(str(exc))
            for contract in active:
                supplier=session.get(Supplier,contract.supplier_id)
                with st.expander(f"{supplier.name} · {contract.title or contract.contract_number} · {contract.contract_type or contract.supplier_type}"):
                    st.write(f"{contract.valid_from:%d.%m.%Y} – {(contract.valid_until or contract.valid_to):%d.%m.%Y} · {contract.currency} · {contract.status}")
                    docs=session.query(ContractDocument).filter_by(contract_id=contract.id).order_by(ContractDocument.uploaded_at.desc()).all()
                    for link in docs:
                        doc=session.get(__import__('database.models',fromlist=['Document']).Document,link.document_id); st.download_button(f"Belgeyi İndir · {doc.original_filename}",load_document_bytes(doc),doc.original_filename,key=f"contract_doc_{link.id}")
        with tabs[1]:
            selected_type=st.selectbox("Hizmet Türü",["Tümü"]+list(ContractPriceService.CONTRACT_TYPES)); shown=rules if selected_type=="Tümü" else [x for x in rules if x.service_type==selected_type]
            st.dataframe(pd.DataFrame([{"Hizmet":x.service_name,"Tür":x.service_type,"Başlangıç":x.valid_from,"Bitiş":x.valid_until,"Model":x.pricing_model,"Temel":x.base_price,"Yetişkin":x.adult_price,"Çocuk":x.child_price,"Döviz":x.currency} for x in shown]),hide_index=True,use_container_width=True)
            if shown:
                rule=st.selectbox("Fiyatı güncelle",shown,format_func=lambda x:f"{x.service_name} · {x.base_price or x.adult_price} {x.currency}"); c1,c2=st.columns(2); new_price=c1.number_input("Yeni fiyat",min_value=0.0); effective=c2.date_input("Yeni fiyat başlangıcı",min_value=rule.valid_from.date(),max_value=rule.valid_until.date())
                if st.button("Yeni Fiyat Versiyonu Oluştur"):
                    try: ContractManagementService.version_price(session,rule,Decimal(str(new_price)),datetime.combine(effective,datetime.min.time())); session.commit(); st.success("Eski dönem kapatıldı, yeni fiyat sürümü oluşturuldu."); st.rerun()
                    except Exception as exc: session.rollback(); st.error(str(exc))
            with st.expander("Tedarikçi Fiyat Karşılaştırması"):
                btype=st.selectbox("Karşılaştırma Türü",ContractPriceService.CONTRACT_TYPES,key="bench_type"); bname=st.text_input("Aynı Hizmet Adı"); bdate=st.date_input("Hizmet Tarihi",key="bench_date")
                if st.button("Karşılaştır"): st.dataframe(pd.DataFrame(ContractManagementService.benchmark(session,btype,bname,bdate)),hide_index=True,use_container_width=True)
        with tabs[2]:
            upcoming=sorted([x for x in contracts if x.status in {"Süresi Yaklaşıyor","Süresi Doldu"}],key=lambda x:x.valid_until or x.valid_to)
            st.dataframe(pd.DataFrame([{"Tedarikçi":session.get(Supplier,x.supplier_id).name,"Sözleşme":x.title,"Bitiş":x.valid_until or x.valid_to,"Durum":x.status} for x in upcoming]),hide_index=True,use_container_width=True)
        with tabs[3]:
            history=session.query(ContractPriceHistory).order_by(ContractPriceHistory.effective_date).all(); st.dataframe(pd.DataFrame([{"Tarih":x.effective_date,"Hizmet":session.get(ContractPriceRule,x.price_rule_id).service_name,"Eski Fiyat":x.old_price,"Yeni Fiyat":x.new_price,"Değişim %":x.change_percentage,"Döviz":x.currency} for x in history]),hide_index=True,use_container_width=True)
            if history:
                chart=pd.DataFrame([{"Tarih":x.effective_date,"Fiyat":float(x.new_price)} for x in history]).set_index("Tarih"); st.line_chart(chart)
        with tabs[4]:
            if tours:
                tour=st.selectbox("Tur",tours,format_func=lambda x:x.name,key="sim_tour"); sim_date=st.date_input("Hizmet Tarihi",date.today()+timedelta(days=30),key="sim_date"); c1,c2,c3=st.columns(3); adults=c1.number_input("Yetişkin",min_value=0,value=20); children=c2.number_input("Çocuk",min_value=0,value=0); rooms=c3.number_input("Oda",min_value=0,value=0); vehicle=st.selectbox("Araç",["Sedan","Minivan","Minibus","Midibus","Bus","VIP","Other"]); language=st.text_input("Rehber Dili",value="Türkçe"); revenue=st.number_input("Beklenen Satış Geliri",min_value=0.0)
                if st.button("Maliyeti Simüle Et",type="primary"):
                    result=ContractManagementService.simulate(session,tour.id,sim_date,adults,children,rooms,vehicle,language,revenue); st.dataframe(pd.DataFrame(result["lines"]),hide_index=True,use_container_width=True); cols=st.columns(5); cols[0].metric("Tedarikçi Maliyeti",result["total_supplier_cost"]); cols[1].metric("Kişi Başı",result["cost_per_passenger"]); cols[2].metric("Brüt Kâr",result["estimated_gross_profit"]); cols[3].metric("Kâr Marjı %",result["expected_profit_margin"]); cols[4].metric("Başa Baş Yolcu",result["break_even_passenger_count"] or "—")
        with tabs[5]:
            upload=st.file_uploader("Excel veya CSV",type=["xlsx","xls","csv"],key="contract_import")
            if upload:
                frame=pd.read_csv(upload) if upload.name.lower().endswith(".csv") else pd.read_excel(upload); st.dataframe(frame.head(100),hide_index=True,use_container_width=True); confirm=st.checkbox("Önizlemeyi kontrol ettim; içe aktar")
                if st.button("Onaylı Aktarımı Başlat",disabled=not confirm):
                    required={"supplier","contract type","service","valid from","valid until","currency"}; normalized={str(c).strip().lower():c for c in frame.columns}; missing_columns=required-set(normalized)
                    if missing_columns: st.error("Eksik sütunlar: "+", ".join(sorted(missing_columns)))
                    else:
                        imported=0
                        try:
                            for _,row in frame.iterrows():
                                supplier=session.query(Supplier).filter(Supplier.name==str(row[normalized["supplier"]]).strip()).first()
                                if not supplier: continue
                                start=pd.to_datetime(row[normalized["valid from"]]).to_pydatetime(); end=pd.to_datetime(row[normalized["valid until"]]).to_pydatetime(); ctype=str(row[normalized["contract type"]]).strip(); service=str(row[normalized["service"]]).strip(); contract,version=ContractManagementService.create_contract(session,supplier.id,ctype,f"{service} İçe Aktarım",start,end,str(row[normalized["currency"]]).strip())
                                ContractManagementService.create_price_rule(session,contract,version,ctype,service,start,end,"Kişi Başı",currency=contract.currency,adult_price=row[normalized.get("adult price",normalized.get("room price",normalized.get("vehicle price",normalized.get("guide price"))))] if any(k in normalized for k in ["adult price","room price","vehicle price","guide price"]) else 0,child_price=row[normalized["child price"]] if "child price" in normalized else 0,tax_rate=row[normalized["tax"]] if "tax" in normalized else 0); imported+=1
                            BusinessAuditService.log(session,"CONTRACT_IMPORT_COMPLETED","supplier_contract",details={"imported":imported}); session.commit(); st.success(f"{imported} sözleşme satırı aktarıldı."); st.rerun()
                        except Exception as exc: session.rollback(); st.error(f"Aktarım geri alındı: {exc}")
    finally: session.close()


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
    page_header("Cari Hesap Mutabakatı", "Müşteri ve tedarikçi hesaplarını otomatik hesaplayın, açık bakiyeleri kontrol edin, mutabakat oluşturun ve farkları inceleyin.")
    session = SessionLocal()
    try:
        if st.button("Kayıtları Şimdi Yenile",type="primary"):
            result=DailyCurrentAccountService.refresh(session);st.success(f"{result['movements_created']} yeni hareket, {result['matches_created']} eşleşme işlendi.");st.rerun()
        CurrentAccountProjectionService.get_or_create_accounts(session);accounts=session.query(CurrentAccount).filter_by(active=True).order_by(CurrentAccount.name).all()
        if not accounts:empty_state("Cari hesap bulunamadı","Müşteri veya tedarikçi ekleyin.");return
        today=datetime.utcnow();customer_ids=[x.id for x in accounts if x.customer_id];supplier_ids=[x.id for x in accounts if x.supplier_id]
        def balance(ids,overdue=False):
            q=session.query(OpenItem).filter(OpenItem.account_id.in_(ids),OpenItem.remaining_amount>0) if ids else session.query(OpenItem).filter(False)
            if overdue:q=q.filter(OpenItem.due_date<today)
            return sum((Decimal(str(x.remaining_amount)) for x in q.all()),Decimal("0"))
        unmatched=session.query(CurrentAccountMovement).filter_by(status="Eşleşmeyen").count();pending=session.query(AccountReconciliation).filter(AccountReconciliation.status.in_(["Hazırlanıyor","Gönderime Hazır","Cevap Bekleniyor"])).count();cards=st.columns(6);cards[0].metric("Toplam Müşteri Alacağı",balance(customer_ids));cards[1].metric("Toplam Tedarikçi Borcu",balance(supplier_ids));cards[2].metric("Vadesi Geçmiş Alacak",balance(customer_ids,True));cards[3].metric("Vadesi Geçmiş Borç",balance(supplier_ids,True));cards[4].metric("Eşleşmeyen Hareket",unmatched);cards[5].metric("Mutabakat Bekleyen Cari",pending)
        f1,f2,f3=st.columns(3);start=f1.date_input("Başlangıç",date.today().replace(day=1));end=f2.date_input("Bitiş",date.today());currency=f3.selectbox("Para Birimi",CurrencyManagementService.CURRENCIES)
        tabs=st.tabs(["Tüm Cariler","Müşteri Carileri","Tedarikçi Carileri","Açık Kalemler","Vadesi Geçmişler","Mutabakatlar","Farklı Kayıtlar"])
        def account_table(rows):
            data=[]
            for account in rows:
                movements=session.query(CurrentAccountMovement).filter_by(account_id=account.id,currency=currency).all();debit=sum((Decimal(str(x.debit)) for x in movements),Decimal("0"));credit=sum((Decimal(str(x.credit)) for x in movements),Decimal("0"));risk=session.query(AccountRiskScore).filter_by(account_id=account.id).order_by(AccountRiskScore.score_date.desc()).first();data.append({"Cari":account.name,"Tür":account.account_type,"Borç":debit,"Alacak":credit,"Bakiye":debit-credit,"Risk":risk.risk_level if risk else "Hesaplanmadı"})
            st.dataframe(pd.DataFrame(data),hide_index=True,use_container_width=True)
        with tabs[0]:account_table(accounts)
        with tabs[1]:account_table([x for x in accounts if x.customer_id])
        with tabs[2]:account_table([x for x in accounts if x.supplier_id])
        with tabs[3]:
            items=session.query(OpenItem).filter(OpenItem.remaining_amount>0,OpenItem.currency==currency).all();st.dataframe(pd.DataFrame([{"Cari":session.get(CurrentAccount,x.account_id).name,"Fatura":x.invoice_number,"Toplam":x.original_amount,"Eşleşen":x.matched_amount,"Kalan":x.remaining_amount,"Vade":x.due_date,"Gecikme":max((today.date()-x.due_date.date()).days,0) if x.due_date else 0,"Durum":x.status} for x in items]),hide_index=True,use_container_width=True)
        with tabs[4]:
            overdue=session.query(OpenItem).filter(OpenItem.remaining_amount>0,OpenItem.currency==currency,OpenItem.due_date<today).all();st.dataframe(pd.DataFrame([{"Cari":session.get(CurrentAccount,x.account_id).name,"Fatura":x.invoice_number,"Kalan":x.remaining_amount,"Vade":x.due_date,"Gün":(today.date()-x.due_date.date()).days} for x in overdue]),hide_index=True,use_container_width=True);st.bar_chart(pd.DataFrame([{"Vade":k,"Tutar":float(v)} for k,v in AccountAnalyticsService.aging(session).items()]).set_index("Vade"))
        selected=st.selectbox("Detay / mutabakat carisi",accounts,format_func=lambda x:f"{x.name} · {x.account_type}")
        with st.expander("Cari Detayı",expanded=True):
            movements=session.query(CurrentAccountMovement).filter(CurrentAccountMovement.account_id==selected.id,CurrentAccountMovement.currency==currency,CurrentAccountMovement.transaction_date>=datetime.combine(start,datetime.min.time()),CurrentAccountMovement.transaction_date<=datetime.combine(end,datetime.max.time())).order_by(CurrentAccountMovement.transaction_date).all();behavior=AccountAnalyticsService.payment_behavior(session,selected.id);opens=session.query(OpenItem).filter_by(account_id=selected.id).all();d1,d2,d3,d4=st.columns(4);d1.metric("Cari Bakiye",sum((Decimal(str(x.debit))-Decimal(str(x.credit)) for x in movements),Decimal("0")));d2.metric("Açık Fatura",sum((Decimal(str(x.remaining_amount)) for x in opens),Decimal("0")));d3.metric("Ort. Ödeme Gecikmesi",behavior["average_payment_delay"]);d4.metric("İşlem Sayısı",len(movements));ledger=pd.DataFrame([{"Tarih":x.transaction_date,"İşlem Türü":x.transaction_type,"Belge No":x.document_number,"Açıklama":x.description,"Borç":x.debit,"Alacak":x.credit,"Para Birimi":x.currency,"Kur":x.exchange_rate,"Yerel Karşılık":x.base_amount,"Bakiye":x.running_balance,"Kaynak":f"{x.source_type} #{x.source_id}","Rezervasyon":x.booking_id,"Tur":x.tour_id,"Fatura":x.invoice_id,"Durum":x.status} for x in movements]);st.dataframe(ledger,hide_index=True,use_container_width=True);st.line_chart(ledger.set_index("Tarih")[["Bakiye"]].astype(float)) if not ledger.empty else None
        with tabs[5]:
            if st.button("Mutabakat Formu Oluştur"):
                rec=AutomaticAccountReconciliationService.create(session,selected,start,end,currency);st.session_state.current_reconciliation_id=rec.id;st.rerun()
            reconciliations=session.query(AccountReconciliation).filter_by(account_id=selected.id).order_by(AccountReconciliation.prepared_at.desc()).all()
            for rec in reconciliations:
                with st.expander(f"{rec.reference_number} · {rec.status} · {rec.closing_balance} {rec.currency}"):
                    st.write(f"Açılış {rec.opening_balance} + Borç {rec.debit_total} - Alacak {rec.credit_total} = **{rec.closing_balance}**");lang=st.radio("Taslak dili",["TR","EN"],horizontal=True,key=f"lang_{rec.id}");st.text_area("Mutabakat Mesajı",AutomaticAccountReconciliationService.draft(selected,rec,lang),key=f"draft_{rec.id}");excel,pdf=AutomaticAccountReconciliationService.exports(session,rec);c1,c2=st.columns(2);c1.download_button("Excel İndir",excel,f"{rec.reference_number}.xlsx",key=f"rex_{rec.id}");c2.download_button("PDF İndir",pdf,f"{rec.reference_number}.pdf","application/pdf",key=f"rpdf_{rec.id}")
                    response=st.selectbox("Karşı Taraf Yanıtı",["Cevap Bekleniyor","Mutabık","Mutabık Değil"],key=f"resp_{rec.id}");counter=st.number_input("Karşı taraf bakiyesi",value=0.0,key=f"counter_{rec.id}");explanation=st.text_area("Açıklama",key=f"expl_{rec.id}");attachment=st.file_uploader("Fark belgesi",type=["pdf","jpg","jpeg","png"],key=f"ratt_{rec.id}")
                    a,b,c=st.columns(3)
                    if a.button("Yanıtı Kaydet",key=f"save_resp_{rec.id}"):
                        try:AutomaticAccountReconciliationService.record_response(session,rec,response,Decimal(str(counter)) if response=="Mutabık Değil" else None,explanation,attachment=(attachment.getvalue(),attachment.name,attachment.type) if attachment else None);st.rerun()
                        except Exception as exc:st.error(str(exc))
                    if b.button("Dönemi Kilitle",disabled=rec.lock_status=="Kilitli",key=f"lock_{rec.id}"):AutomaticAccountReconciliationService.lock(session,rec);st.rerun()
                    if c.button("Dönemi Yeniden Aç",disabled=rec.lock_status!="Kilitli",key=f"reopen_{rec.id}"):AutomaticAccountReconciliationService.reopen(session,rec);st.rerun()
        with tabs[6]:
            differences=session.query(AccountReconciliationDifference).join(AccountReconciliation).filter(AccountReconciliation.account_id==selected.id).all();st.dataframe(pd.DataFrame([{"Tür":x.difference_type,"Önem":x.severity,"Tutar":x.amount,"Döviz":x.currency,"Açıklama":x.explanation,"Durum":x.status} for x in differences]),hide_index=True,use_container_width=True)
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
