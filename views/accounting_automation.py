import json
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker

from database.db import engine
from database.models import (
    ApprovalRequest, AuditLog, BankAccount, BankReconciliationMatch,
    BankTransaction, Booking, HotelBooking, HotelReconciliation,
    ReservationCandidate, RestaurantReconciliation, Supplier, SupplierPayment, Transaction,
)
from services.accounting_automation_service import (
    ApprovalWorkflowService, AuditLogService, BankStatementService,
    BankReconciliationService, DocumentMatchingService, FinancialValidationService,
    ReconciliationExportService,
)
from services.drive_import_service import ExcelFileReader, ValueNormalizationService
from utils.ui import empty_state, page_header


Session = sessionmaker(bind=engine)


def _steps(labels, active):
    st.progress((active + 1) / len(labels), text=" · ".join(f"{i + 1}. {label}" for i, label in enumerate(labels)))


def _decimal_input(label, key, value=0.0):
    return Decimal(str(st.number_input(label, value=float(value), min_value=0.0, key=key)))


def _result(result):
    cols = st.columns(4)
    cols[0].metric("Durum", result["status"])
    cols[1].metric("Beklenen", f"{result.get('expected_total', 0):,.2f}")
    cols[2].metric("Belge Toplamı", f"{result.get('invoice_total', 0):,.2f}")
    cols[3].metric("Fark", f"{result.get('difference', 0):,.2f}")
    differences = result.get("differences") or []
    if differences:
        st.dataframe(pd.DataFrame(differences).rename(columns={"field": "Kontrol Alanı", "incoming": "Belge", "expected": "Acente Kaydı", "status": "Durum"}), hide_index=True, use_container_width=True)
    else: st.success("Kontrol edilen alanlar toleranslar içinde eşleşti.")


def render_restaurant_reconciliation():
    page_header("Restoran Faturası - Voucher Mutabakatı", "Ücretsiz kişi haklarını ve anlaşmalı fiyatı deterministik olarak kontrol edin.")
    _steps(["Belge Bilgileri", "Voucher Kontrolü", "Farkları İncele", "Onaya Gönder"], 1)
    session = Session()
    try:
        suppliers = session.query(Supplier).order_by(Supplier.name).all()
        vouchers = session.query(Booking).filter(Booking.voucher_number.isnot(None)).order_by(Booking.booking_number.desc()).all()
        if not suppliers or not vouchers:
            empty_state("Mutabakat için kayıt eksik", "En az bir restoran/tedarikçi ve voucher numaralı rezervasyon kaydedin.")
            return
        with st.form("restaurant_reconciliation_form"):
            c1, c2 = st.columns(2)
            supplier = c1.selectbox("Restoran", suppliers, format_func=lambda x: x.name)
            booking = c2.selectbox("Voucher / rezervasyon", vouchers, format_func=lambda x: f"{x.voucher_number} · {x.booking_number}")
            invoice_number = c1.text_input("Fatura numarası")
            total_service = c2.number_input("Toplam hizmet alan kişi", min_value=0, value=int(booking.passenger_count or 0))
            free_guide = c1.number_input("Ücretsiz rehber", min_value=0, value=1)
            free_driver = c2.number_input("Ücretsiz şoför", min_value=0, value=1)
            other_free = c1.number_input("Diğer ücretsiz kişi", min_value=0, value=0)
            agreed = _decimal_input("Anlaşılan kişi başı fiyat", "restaurant_agreed", booking.unit_price or 0)
            invoiced = _decimal_input("Faturadaki kişi başı fiyat", "restaurant_invoiced", booking.unit_price or 0)
            approved_extras = _decimal_input("Onaylı ek kalemler", "restaurant_extras")
            unauthorized = _decimal_input("Onaysız içecek / ek kalem", "restaurant_unauthorized")
            tax = _decimal_input("Vergi", "restaurant_tax")
            invoice_total = _decimal_input("Fatura toplamı", "restaurant_total")
            actor = st.text_input("İnceleyen muhasebeci")
            submitted = st.form_submit_button("Analiz Et ve Onaya Gönder", type="primary")
        if submitted:
            duplicate_invoice = bool(invoice_number and session.query(RestaurantReconciliation).filter(RestaurantReconciliation.invoice_number == invoice_number).first())
            duplicate_voucher = bool(session.query(RestaurantReconciliation).filter(RestaurantReconciliation.voucher_number == booking.voucher_number).first())
            document = {"supplier_name": supplier.name, "invoice_number": invoice_number, "voucher_number": booking.voucher_number, "total_service_count": total_service, "invoiced_unit_price": invoiced, "approved_additional_items": approved_extras, "unauthorized_extras": unauthorized, "tax_amount": tax, "invoice_total": invoice_total, "duplicate_invoice": duplicate_invoice, "duplicate_voucher": duplicate_voucher}
            agency = {"supplier_name": supplier.name, "voucher_number": booking.voucher_number, "passenger_count": booking.passenger_count, "free_guide_count": free_guide, "free_driver_count": free_driver, "other_free_person_count": other_free, "agreed_unit_price": agreed, "currency": booking.currency}
            result = FinancialValidationService.restaurant(document, agency)
            record = RestaurantReconciliation(supplier_id=supplier.id, voucher_number=booking.voucher_number, invoice_number=invoice_number or None, calculated_values={key: str(value) for key, value in result.items() if key != "differences"}, differences=result["differences"], expected_total=result["expected_total"], invoice_total=result["invoice_total"], potential_overpayment=result["potential_overpayment"], status="Onay Bekliyor")
            session.add(record); session.flush()
            ApprovalWorkflowService.create(session, "Restoran mutabakatı", "Onay sonrası faturaya veya tedarikçi ödemesine kaydet", source_entity_type="restaurant_reconciliation", source_entity_id=record.id, before=agency, after=document, differences=result["differences"], financial_effect=result["difference"], actor=actor, commit=False)
            AuditLogService.log(session, "restaurant_reconciliation_analyzed", entity_type="restaurant_reconciliation", entity_id=record.id, new_values=result, actor_name=actor)
            session.commit(); st.session_state.restaurant_result = result
        if st.session_state.get("restaurant_result"):
            _result(st.session_state.restaurant_result)
            st.metric("Önlenebilecek fazla ödeme", f"{st.session_state.restaurant_result['potential_overpayment']:,.2f}")
            st.success("Analiz kalıcı onay kuyruğuna gönderildi; henüz finansal kayıt oluşturulmadı.")
    finally: session.close()


def render_hotel_reconciliation():
    page_header("Otel Faturası - Rezervasyon Mutabakatı", "Gece, oda, fiyat ve ek hizmetleri rezervasyonla karşılaştırın.")
    _steps(["Faturayı Seç", "Rezervasyonu Seç", "Analiz", "Fark Kontrolü", "Onaya Gönder"], 2)
    session = Session()
    try:
        stays = session.query(HotelBooking).join(HotelBooking.hotel).join(HotelBooking.booking).order_by(HotelBooking.id.desc()).all()
        if not stays: empty_state("Otel rezervasyonu bulunamadı", "Önce bir otel rezervasyonu kaydedin."); return
        with st.form("hotel_reconciliation_form"):
            stay = st.selectbox("Otel rezervasyonu", stays, format_func=lambda x: f"#{x.booking_id} · {x.hotel.name if x.hotel else 'Otel kaydı bulunamadı'} · {x.nights} gece")
            invoice_number = st.text_input("Fatura numarası")
            c1, c2 = st.columns(2)
            invoice_nights = c1.number_input("Faturadaki gece", min_value=0, value=int(stay.nights or 0))
            invoice_rooms = c2.number_input("Faturadaki oda", min_value=0, value=int(stay.room_count or 0))
            invoiced_rate = _decimal_input("Faturadaki oda fiyatı", "hotel_rate", stay.price_per_room or 0)
            approved_extras = _decimal_input("Onaylı ek hizmet", "hotel_extras")
            unapproved_extras = _decimal_input("Onaysız minibar / hizmet", "hotel_unapproved")
            tax = _decimal_input("Vergi ve şehir vergisi", "hotel_tax")
            invoice_total = _decimal_input("Fatura toplamı", "hotel_total")
            actor = st.text_input("İnceleyen muhasebeci", key="hotel_actor")
            submitted = st.form_submit_button("Analiz Et ve Onaya Gönder", type="primary")
        if submitted:
            duplicate_invoice = bool(invoice_number and session.query(HotelReconciliation).filter(HotelReconciliation.invoice_number == invoice_number).first())
            document = {"invoice_number": invoice_number, "nights": invoice_nights, "room_count": invoice_rooms, "room_type": stay.room_type, "board_type": stay.board_type, "invoiced_room_rate": invoiced_rate, "approved_extras": approved_extras, "unapproved_extras": unapproved_extras, "tax_amount": tax, "invoice_total": invoice_total, "duplicate_invoice": duplicate_invoice}
            booking = {"checkin_date": stay.checkin_date, "checkout_date": stay.checkout_date, "nights": stay.nights, "room_count": stay.room_count, "room_type": stay.room_type, "board_type": stay.board_type, "agreed_room_rate": stay.price_per_room, "adult_count": stay.adult_count, "child_count": stay.child_count}
            result = FinancialValidationService.hotel(document, booking)
            record = HotelReconciliation(hotel_id=stay.hotel_id, booking_id=stay.booking_id, invoice_number=invoice_number or None, calculated_values={key: str(value) for key, value in result.items() if key != "differences"}, differences=result["differences"], expected_total=result["expected_total"], invoice_total=result["invoice_total"], status="Onay Bekliyor")
            session.add(record); session.flush()
            ApprovalWorkflowService.create(session, "Otel mutabakatı", "Onay sonrası faturaya veya tedarikçi ödemesine kaydet", source_entity_type="hotel_reconciliation", source_entity_id=record.id, before=booking, after=document, differences=result["differences"], financial_effect=result["difference"], actor=actor, commit=False)
            AuditLogService.log(session, "hotel_reconciliation_analyzed", entity_type="hotel_reconciliation", entity_id=record.id, new_values=result, actor_name=actor)
            session.commit(); st.session_state.hotel_result = result
        if st.session_state.get("hotel_result"): _result(st.session_state.hotel_result); st.success("Analiz onay kuyruğuna gönderildi.")
    finally: session.close()


def render_supplier_payment_reconciliation():
    page_header("Tedarikçi Ödeme Mutabakatı", "Fatura borcunu, önceki ödemeleri ve yeni ödeme tutarını kontrol edin.")
    _steps(["Borcu Seç", "Ödemeyi Kontrol Et", "Riskleri İncele", "Onaya Gönder"], 1)
    session = Session()
    try:
        debts = session.query(SupplierPayment).order_by(SupplierPayment.id.desc()).all()
        if not debts: empty_state("Tedarikçi borcu bulunamadı", "Önce bir tedarikçi borcu veya faturası kaydedin."); return
        with st.form("supplier_payment_reconciliation_form"):
            debt = st.selectbox("Tedarikçi borcu", debts, format_func=lambda x: f"#{x.id} · {x.invoice_reference or 'Belge yok'} · {x.remaining_amount} {x.currency}")
            amount = _decimal_input("Planlanan ödeme", "supplier_recon_amount", debt.remaining_amount or 0)
            currency = st.selectbox("Para birimi", ["TRY", "EUR", "USD", "GBP"], index=["TRY", "EUR", "USD", "GBP"].index(debt.currency) if debt.currency in ["TRY", "EUR", "USD", "GBP"] else 0)
            reference = st.text_input("Banka / ödeme referansı")
            document_present = st.checkbox("Ödeme belgesi mevcut", value=True)
            invoice_approved = st.checkbox("Fatura mutabakatı onaylandı")
            actor = st.text_input("İnceleyen muhasebeci", key="supplier_actor")
            submitted = st.form_submit_button("Kontrol Et ve Onaya Gönder", type="primary")
        if submitted:
            duplicate = bool(reference and session.query(SupplierPayment).filter(SupplierPayment.document_reference == reference).first())
            invoice = {"grand_total": debt.total_debt, "currency": debt.currency}
            payment = {"amount": amount, "currency": currency, "reference": reference, "document_present": document_present, "invoice_approved": invoice_approved}
            result = FinancialValidationService.supplier_payment(invoice, payment, debt.paid_amount)
            if duplicate: result["issues"].append("Mükerrer ödeme referansı"); result["status"] = "Mükerrer Ödeme Şüphesi"
            ApprovalWorkflowService.create(session, "Tedarikçi ödemesi", "Onay sonrası tedarikçi bakiyesini güncelle", source_entity_type="supplier_payment", source_entity_id=debt.id, before={"paid_amount": debt.paid_amount, "remaining_amount": debt.remaining_amount}, after=payment, differences=result["issues"], financial_effect=amount, actor=actor)
            st.session_state.supplier_payment_result = result
        if st.session_state.get("supplier_payment_result"):
            result = st.session_state.supplier_payment_result
            st.info(f"Durum: {result['status']} · Kalan bakiye: {result['remaining_balance']}")
            for issue in result["issues"]: st.warning(issue)
            st.success("Ödeme önerisi onay kuyruğuna kaydedildi; tedarikçi bakiyesi değiştirilmedi.")
    finally: session.close()


BANK_FIELDS = {
    "bank_account": "Banka hesabı", "transaction_date": "İşlem tarihi", "value_date": "Valör tarihi",
    "description": "Açıklama", "reference_number": "Referans numarası", "counterparty": "Karşı taraf",
    "counterparty_iban": "Karşı taraf IBAN", "currency": "Para birimi", "debit_amount": "Borç",
    "credit_amount": "Alacak", "balance": "Bakiye",
}


def render_bank_reconciliation():
    page_header("Banka Hareketleri ve Mutabakat", "Ekstreyi yükleyin, eşleşme önerilerini inceleyin ve yalnızca onayla muhasebeleştirin.")
    _steps(["Ekstre Yükle", "Hareketleri Kontrol Et", "Eşleşmeleri İncele", "Onayla", "Muhasebeleştir"], 0)
    session = Session()
    try:
        accounts = session.query(BankAccount).order_by(BankAccount.bank_name).all()
        uploaded = st.file_uploader("Banka ekstresi", type=["xlsx", "xls", "csv"], key="bank_statement")
        if uploaded:
            frame, header = ExcelFileReader.analyze(uploaded.getvalue(), uploaded.name)
            st.caption(f"Başlık satırı {header + 1}. satırda bulundu; {len(frame)} hareket okunacak.")
            st.dataframe(frame.head(30), hide_index=True, use_container_width=True)
            account = st.selectbox("Banka hesabı", [None] + accounts, format_func=lambda x: "Hesap seçilmedi" if x is None else f"{x.bank_name} · {x.currency}")
            mapping = {}
            options = ["Kullanma"] + list(BANK_FIELDS)
            for column in frame.columns:
                normalized = str(column).casefold()
                guess = next((key for key, label in BANK_FIELDS.items() if key.replace("_", " ") in normalized or label.casefold() in normalized), "Kullanma")
                selected = st.selectbox(f"{column} alanı", options, index=options.index(guess), format_func=lambda x: "Kullanma" if x == "Kullanma" else BANK_FIELDS[x], key=f"bank_map_{column}")
                if selected != "Kullanma": mapping[str(column)] = selected
            approved = st.checkbox("Hareketleri ve kolon eşleştirmelerini kontrol ettim.")
            if st.button("Ekstreyi Kaydet", disabled=not approved or "transaction_date" not in mapping, type="primary"):
                try:
                    batch, result = BankStatementService.import_rows(session, uploaded.name, uploaded.getvalue(), frame.to_dict("records"), mapping, account.id if account else None)
                    st.success(f"Ekstre #{batch.id}: {result['imported']} yeni hareket, {result['duplicates']} mükerrer.")
                except Exception as exc: session.rollback(); st.error(f"Ekstre kaydedilemedi; hiçbir kısmi kayıt bırakılmadı: {exc}")
        st.subheader("Kaydedilmiş Hareketler")
        transactions = session.query(BankTransaction).order_by(BankTransaction.transaction_date.desc()).limit(100).all()
        if transactions:
            selected_tx = st.selectbox("Hareket", transactions, format_func=lambda x: f"#{x.id} · {x.transaction_date.strftime('%d.%m.%Y') if x.transaction_date else 'Tarih yok'} · {x.amount} {x.currency} · {x.description[:45] if x.description else ''}")
            candidates = DocumentMatchingService.bank_candidates(session, selected_tx)
            if candidates:
                action = st.selectbox("İşlem", ["Tahsilata Bağla", "Tedarikçi Ödemesine Bağla", "Gelir Olarak Kaydet", "Gider Olarak Kaydet", "Bölerek Eşleştir", "Birden Fazla Kaydı Birleştir", "Yoksay", "Manuel İncelemeye Gönder"])
                selected_candidates = st.multiselect("Eşleşme önerileri", candidates, default=candidates[:1], format_func=lambda x: f"{x['entity_type']} #{x['entity_id']} · %{x['score']} · {x['reason']}")
                allocations = []
                for index, candidate in enumerate(selected_candidates):
                    allocated = st.number_input(f"{candidate['entity_type']} #{candidate['entity_id']} için ayrılan tutar", min_value=0.0, value=float(min(abs(selected_tx.amount or 0), candidate.get("amount") or abs(selected_tx.amount or 0))), key=f"bank_allocation_{selected_tx.id}_{index}")
                    allocations.append({**candidate, "amount": str(allocated)})
                actor = st.text_input("Onaylayacak muhasebeci", key="bank_actor")
                if st.button("Eşleşmeyi Onaya Gönder"):
                    try:
                        BankReconciliationService.validate_allocations(selected_tx, allocations)
                        ApprovalWorkflowService.create(session, "Banka hareketi eşleşmesi", action, source_entity_type="bank_transaction", source_entity_id=selected_tx.id, before={"status": selected_tx.status}, after={"allocations": allocations}, differences=[], financial_effect=selected_tx.amount, actor=actor, commit=False)
                        selected_tx.status = "Onay Bekliyor"; session.commit(); st.success("Eşleşme onay kuyruğuna gönderildi.")
                    except ValueError as exc: st.error(str(exc))
            else: st.info("Bu hareket için güçlü bir eşleşme bulunamadı; manuel incelemeye gönderebilirsiniz.")
        else: empty_state("Banka hareketi yok", "İlk ekstreyi yükleyerek başlayın.")
    finally: session.close()


def _apply_approval(session, request):
    after = request.after_values or {}
    if request.request_type == "Tedarikçi ödemesi":
        payment = session.get(SupplierPayment, request.source_entity_id)
        amount = Decimal(str(after.get("amount") or 0))
        payment.paid_amount = Decimal(str(payment.paid_amount or 0)) + amount
        payment.remaining_amount = Decimal(str(payment.total_debt or 0)) - payment.paid_amount
        payment.document_reference = after.get("reference") or payment.document_reference
        payment.payment_date = datetime.utcnow(); payment.payment_status = "Tam Ödendi" if payment.remaining_amount <= 0 else "Kısmen Ödendi"
    elif request.request_type == "Banka hareketi eşleşmesi":
        tx = session.get(BankTransaction, request.source_entity_id)
        BankReconciliationService.apply(session, tx, after["allocations"])
    elif request.request_type in {"Restoran mutabakatı", "Otel mutabakatı"}:
        source = session.get(RestaurantReconciliation if request.request_type.startswith("Restoran") else HotelReconciliation, request.source_entity_id)
        source.status = "Onaylandı"
    elif request.request_type == "WhatsApp reservation candidate":
        candidate = session.get(ReservationCandidate, request.source_entity_id)
        from backend.services.communication_services import ReservationCandidateService
        ReservationCandidateService.convert_to_booking(session, candidate)


def render_approval_queue():
    page_header("Onay Bekleyen İşlemler", "Önerileri inceleyin; finansal etki yalnızca açık onayınızdan sonra uygulanır.")
    session = Session()
    try:
        statuses = ["Onay Bekliyor", "Taslak", "Analiz Edildi", "Düzeltme İstendi", "Onaylandı", "Reddedildi", "İptal Edildi", "Süresi Geçti"]
        f1, f2, f3, f4 = st.columns(4)
        status = f1.selectbox("Durum", statuses); request_type = f2.selectbox("Tür", ["Tümü"] + [row[0] for row in session.query(ApprovalRequest.request_type).distinct().all()]); severity = f3.selectbox("Önem", ["Tümü", "Bilgi", "Hatırlatma", "Dikkat", "Kritik"]); source = f4.selectbox("Kaynak", ["Tümü"] + [row[0] for row in session.query(ApprovalRequest.source).filter(ApprovalRequest.source.isnot(None)).distinct().all()])
        query = session.query(ApprovalRequest).filter(ApprovalRequest.status == status)
        if request_type != "Tümü": query = query.filter(ApprovalRequest.request_type == request_type)
        if severity != "Tümü": query = query.filter(ApprovalRequest.severity == severity)
        if source != "Tümü": query = query.filter(ApprovalRequest.source == source)
        requests = query.order_by(ApprovalRequest.priority_score.desc(), ApprovalRequest.due_date, ApprovalRequest.created_at.desc()).all()
        if not requests: empty_state("Bu durumda işlem yok", "Filtreyi değiştirerek diğer işlemleri görebilirsiniz."); return
        for request in requests:
            with st.expander(f"#{request.id} · {request.request_type} · {request.proposed_action}", expanded=request.status == "Onay Bekliyor"):
                st.write(f"**Öncelik:** {request.priority_score or 0} · **Önem:** {request.severity or 'Bilgi'} · **Kaynak:** {request.source or '—'} · **Finansal etki:** {request.financial_effect or 0} · **Vade:** {request.due_date or '—'}")
                st.caption(f"Oluşturulma: {request.created_at:%d.%m.%Y %H:%M} · AI güveni: {request.ai_confidence or '—'}")
                c1, c2 = st.columns(2)
                c1.markdown("**Önceki değerler**"); c1.json(request.before_values or {})
                c2.markdown("**Önerilen değerler**"); c2.json(request.after_values or {})
                if request.detected_differences: st.warning("Tespit edilen farklar: " + json.dumps(request.detected_differences, ensure_ascii=False, default=str))
                if request.deterministic_checks: st.json(request.deterministic_checks)
                actor = st.text_input("Muhasebeci adı", value=request.approver_name or "", key=f"approval_actor_{request.id}")
                note = st.text_area("Karar notu", key=f"approval_note_{request.id}")
                decision = st.radio("Karar", ["Onaylandı", "Reddedildi", "Düzeltme İstendi", "Onay Bekliyor", "İptal Edildi"], horizontal=True, key=f"approval_decision_{request.id}")
                confirm = st.checkbox("İşlemin kaynağını, farklarını ve finansal etkisini kontrol ettim.", key=f"approval_confirm_{request.id}")
                if st.button("Kararı Kaydet", disabled=not confirm, type="primary", key=f"approval_save_{request.id}"):
                    try:
                        ApprovalWorkflowService.decide(session, request, decision, actor, note, _apply_approval)
                        st.success("Karar ve işlem geçmişi kaydedildi."); st.rerun()
                    except Exception as exc: st.error(f"Karar uygulanamadı; değişiklikler geri alındı: {exc}")
    finally: session.close()


def render_audit_history():
    page_header("İşlem Geçmişi", "Dosya, aktarım, mutabakat, onay ve kayıt değişikliklerini izleyin.")
    session = Session()
    try:
        start, end = st.date_input("Tarih aralığı", value=(datetime.now().date().replace(day=1), datetime.now().date()))
        action = st.text_input("İşlem ara")
        actor = st.text_input("Muhasebeci ara")
        query = session.query(AuditLog).filter(AuditLog.created_at >= datetime.combine(start, datetime.min.time()), AuditLog.created_at <= datetime.combine(end, datetime.max.time()))
        if action: query = query.filter(AuditLog.event_type.ilike(f"%{action}%"))
        if actor: query = query.filter(AuditLog.actor_name.ilike(f"%{actor}%"))
        logs = query.order_by(AuditLog.created_at.desc()).limit(2000).all()
        rows = [{"Tarih": item.created_at, "İşlem": item.action or item.event_type, "Modül": item.source, "Kayıt Türü": item.entity_type, "Kayıt No": item.entity_id, "Durum": item.status, "Muhasebeci": item.actor_name, "Aktarım No": item.batch_id, "Mutabakat No": item.reconciliation_id, "Neden": item.reason, "Önce": json.dumps(item.old_values, ensure_ascii=False, default=str), "Sonra": json.dumps(item.new_values, ensure_ascii=False, default=str)} for item in logs]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.download_button("Excel Olarak İndir", ReconciliationExportService.excel(rows, "İşlem Geçmişi"), "islem-gecmisi.xlsx")
        st.download_button("PDF Olarak İndir", ReconciliationExportService.pdf(rows, "İşlem Geçmişi"), "islem-gecmisi.pdf", "application/pdf")
        st.download_button("CSV Olarak İndir", ReconciliationExportService.csv(rows), "islem-gecmisi.csv", "text/csv")
    finally: session.close()
