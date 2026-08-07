import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from sqlalchemy import or_

from database.models import (
    AccountReconciliation, AccountReconciliationDifference, AccountReconciliationResponse,
    AccountRiskScore, AuditLog, BankTransaction, Booking, Collection, CurrentAccount,
    CurrentAccountMovement, ExchangeDifferenceEntry, OpenItem, OpenItemMatch,
    Supplier, SupplierPayment, Customer,
)
from services.accounting_automation_service import ReconciliationExportService
from services.storage_service import store_document_bytes

ZERO = Decimal("0")


def money(value): return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class CurrentAccountAudit:
    @staticmethod
    def log(session, event, entity_type, entity_id=None, before=None, after=None):
        session.add(AuditLog(event_type=event, entity_type=entity_type, entity_id=entity_id, action=event, old_values=before, new_values=after, source="current_account", status="Tamamlandı"))


class CurrentAccountProjectionService:
    ACCOUNT_TYPES = ("Müşteri Carisi", "Tedarikçi Carisi", "Otel Carisi", "Restoran Carisi", "Transfer Firması Carisi", "Rehber Carisi", "Yerel Acenta Carisi")
    CANCELLED = ("İptal", "İptal edildi", "İptal Edildi", "Cancelled", "Canceled")

    @staticmethod
    def get_or_create_accounts(session):
        created = 0
        for customer in session.query(Customer).all():
            if not session.query(CurrentAccount).filter_by(customer_id=customer.id).first():
                account=CurrentAccount(account_type="Müşteri Carisi",customer_id=customer.id,name=f"{customer.first_name} {customer.last_name or ''}".strip(),base_currency="TRY"); session.add(account); session.flush(); CurrentAccountAudit.log(session,"CURRENT_ACCOUNT_CREATED","current_account",account.id); created+=1
        type_map={"Otel":"Otel Carisi","Restoran":"Restoran Carisi","Transfer":"Transfer Firması Carisi","Rehber":"Rehber Carisi","Yerel acenta":"Yerel Acenta Carisi"}
        for supplier in session.query(Supplier).all():
            if not session.query(CurrentAccount).filter_by(supplier_id=supplier.id).first():
                account=CurrentAccount(account_type=type_map.get(supplier.supplier_type,"Tedarikçi Carisi"),supplier_id=supplier.id,name=supplier.name,base_currency="TRY"); session.add(account); session.flush(); CurrentAccountAudit.log(session,"CURRENT_ACCOUNT_CREATED","current_account",account.id); created+=1
        session.commit(); return created

    @staticmethod
    def _hash(data): return hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()

    @classmethod
    def _upsert(cls,session,account,source_type,source_id,date,kind,debit,credit,currency,rate,document=None,description=None,booking_id=None,tour_id=None,invoice_id=None,status="Aktif"):
        payload={"source_type":source_type,"source_id":source_id,"date":date,"debit":str(debit),"credit":str(credit),"currency":currency,"rate":str(rate),"document":document}; digest=cls._hash(payload)
        existing=session.query(CurrentAccountMovement).filter_by(source_type=source_type,source_id=source_id).first()
        if existing:
            if existing.source_hash==digest:return existing,False
            locked=session.query(AccountReconciliation).filter(AccountReconciliation.account_id==account.id,AccountReconciliation.lock_status=="Kilitli",AccountReconciliation.period_start<=existing.transaction_date,AccountReconciliation.period_end>=existing.transaction_date).first()
            if locked:
                session.add(AccountReconciliationDifference(reconciliation_id=locked.id,difference_type="historical balance mismatch",severity="Kritik",amount=money(debit)-money(credit),currency=currency,source_type=source_type,source_id=source_id,explanation="Kilitli dönemdeki kaynak kayıt değişti; dönem yeniden açılmadan hareket güncellenmedi.")); return existing,False
            before={"debit":str(existing.debit),"credit":str(existing.credit),"source_hash":existing.source_hash}; existing.transaction_date=date;existing.transaction_type=kind;existing.debit=money(debit);existing.credit=money(credit);existing.currency=currency;existing.exchange_rate=Decimal(str(rate or 1));existing.base_amount=money((money(debit)-money(credit))*Decimal(str(rate or 1)));existing.source_hash=digest;existing.updated_at=datetime.utcnow();CurrentAccountAudit.log(session,"CURRENT_ACCOUNT_MOVEMENT_CREATED","current_account_movement",existing.id,before,{"refreshed":True});return existing,False
        row=CurrentAccountMovement(account_id=account.id,transaction_date=date,transaction_type=kind,document_number=document,description=description,debit=money(debit),credit=money(credit),currency=currency,exchange_rate=Decimal(str(rate or 1)),base_amount=money((money(debit)-money(credit))*Decimal(str(rate or 1))),source_type=source_type,source_id=source_id,source_hash=digest,booking_id=booking_id,tour_id=tour_id,invoice_id=invoice_id,status=status);session.add(row);session.flush();CurrentAccountAudit.log(session,"CURRENT_ACCOUNT_MOVEMENT_CREATED","current_account_movement",row.id,None,{"source_type":source_type,"source_id":source_id});return row,True

    @classmethod
    def rebuild(cls,session):
        cls.get_or_create_accounts(session); created=0
        for account in session.query(CurrentAccount).filter_by(active=True).all():
            if account.customer_id:
                bookings=session.query(Booking).filter(Booking.customer_id==account.customer_id,or_(Booking.booking_status.is_(None),Booking.booking_status.notin_(cls.CANCELLED))).all()
                for row in bookings:
                    _,new=cls._upsert(session,account,"customer_invoice",row.id,row.booking_date or row.created_at,"Fatura",row.grand_total,0,row.currency,row.exchange_rate,row.booking_number,f"Rezervasyon faturası {row.booking_number}",row.id,row.tour_id);created+=new
                    for payment in session.query(Collection).filter_by(booking_id=row.id).all():
                        amount=money(payment.amount);kind="Tahsilat" if amount>=0 else "İade";_,new=cls._upsert(session,account,"collection",payment.id,payment.collection_date,kind,0 if amount>=0 else abs(amount),amount if amount>=0 else 0,payment.currency,payment.exchange_rate,payment.receipt_number,payment.notes,row.id,row.tour_id);created+=new
            else:
                for row in session.query(SupplierPayment).filter_by(supplier_id=account.supplier_id).filter(~SupplierPayment.payment_status.in_(["Reddedildi","Mükerrer"])).all():
                    _,new=cls._upsert(session,account,"supplier_invoice",row.id,row.service_date or row.due_date or datetime.utcnow(),"Fatura",row.total_debt,0,row.currency,row.exchange_rate,row.invoice_reference,row.notes,row.booking_id,row.tour_id);created+=new
                    if money(row.paid_amount)>0:
                        _,new=cls._upsert(session,account,"supplier_payment",row.id,row.payment_date or row.due_date or datetime.utcnow(),"Ödeme",0,row.paid_amount,row.currency,row.exchange_rate,row.document_reference,row.notes,row.booking_id,row.tour_id);created+=new
            name=account.name.casefold()
            for bank in session.query(BankTransaction).filter(BankTransaction.status.in_(["Yeni","Eşleşmedi","Onay Bekliyor"])).all():
                if name and name in (bank.counterparty or bank.description or "").casefold():
                    debit=bank.debit_amount or (abs(bank.amount) if money(bank.amount)<0 else 0);credit=bank.credit_amount or (bank.amount if money(bank.amount)>0 else 0);_,new=cls._upsert(session,account,"bank_transaction",bank.id,bank.transaction_date or bank.created_at,"Manuel Hareket",debit,credit,bank.currency,1,bank.reference_number,bank.description,status="Eşleşmeyen");created+=new
        cls._running_balances(session);session.commit();return created

    @staticmethod
    def _running_balances(session):
        for account in session.query(CurrentAccount).all():
            by_currency={}
            for row in session.query(CurrentAccountMovement).filter_by(account_id=account.id).order_by(CurrentAccountMovement.transaction_date,CurrentAccountMovement.id):
                balance=by_currency.get(row.currency,ZERO)+money(row.debit)-money(row.credit);row.running_balance=money(balance);by_currency[row.currency]=balance


class OpenItemMatchingService:
    @staticmethod
    def rebuild_open_items(session,account_id=None):
        query=session.query(CurrentAccountMovement).filter(CurrentAccountMovement.transaction_type=="Fatura");query=query.filter_by(account_id=account_id) if account_id else query
        for movement in query.all():
            if not session.query(OpenItem).filter_by(movement_id=movement.id).first():session.add(OpenItem(account_id=movement.account_id,movement_id=movement.id,invoice_number=movement.document_number,original_amount=movement.debit,remaining_amount=movement.debit,currency=movement.currency,due_date=OpenItemMatchingService._due_date(session,movement),status="Açık"))
        session.flush();return OpenItemMatchingService.auto_match(session,account_id)

    @staticmethod
    def _due_date(session,movement):
        if movement.source_type=="customer_invoice":return session.get(Booking,movement.source_id).final_payment_date
        if movement.source_type=="supplier_invoice":return session.get(SupplierPayment,movement.source_id).due_date
        return None

    @staticmethod
    def _rule(invoice,payment):
        if invoice.document_number and invoice.document_number==payment.document_number:return "exact invoice number",100
        if invoice.booking_id and invoice.booking_id==payment.booking_id:return "exact reservation number",95
        if invoice.currency==payment.currency and money(invoice.debit)==money(payment.credit) and abs((invoice.transaction_date-payment.transaction_date).days)<=7:return "exact amount + close date",80
        if invoice.account_id==payment.account_id and invoice.currency==payment.currency and abs((invoice.transaction_date-payment.transaction_date).days)<=15:return "account + amount + date tolerance",70
        return None,0

    @classmethod
    def auto_match(cls,session,account_id=None):
        items=session.query(OpenItem).filter(OpenItem.status.in_(["Açık","Kısmen Kapandı","Eksik Ödeme"]));items=items.filter_by(account_id=account_id) if account_id else items;matched=0
        for item in items.order_by(OpenItem.due_date,OpenItem.id).all():
            invoice=session.get(CurrentAccountMovement,item.movement_id);payments=session.query(CurrentAccountMovement).filter(CurrentAccountMovement.account_id==item.account_id,CurrentAccountMovement.currency==item.currency,CurrentAccountMovement.credit>0,CurrentAccountMovement.transaction_type.in_(["Tahsilat","Ödeme","İade","Manuel Hareket"])).all()
            for payment in payments:
                used=sum((money(x[0]) for x in session.query(OpenItemMatch.matched_amount).filter_by(payment_movement_id=payment.id).all()),ZERO);available=money(payment.credit)-used
                if available<=0:continue
                rule,confidence=cls._rule(invoice,payment)
                if not rule:continue
                amount=min(money(item.remaining_amount),available);match=OpenItemMatch(open_item_id=item.id,payment_movement_id=payment.id,matched_amount=amount,match_rule=rule,confidence=confidence);session.add(match);item.matched_amount=money(item.matched_amount)+amount;item.remaining_amount=money(item.original_amount)-money(item.matched_amount);item.status="Tam Kapandı" if item.remaining_amount==0 else "Kısmen Kapandı";matched+=1;CurrentAccountAudit.log(session,"OPEN_ITEM_MATCHED","open_item",item.id,None,{"payment_movement_id":payment.id,"amount":str(amount),"rule":rule})
                if item.remaining_amount<=0:break
        session.commit();return matched

    @staticmethod
    def manual_match(session,open_item,payments,allocations):
        total=ZERO
        for payment,amount in zip(payments,allocations):
            amount=money(amount);existing=session.query(OpenItemMatch).filter_by(open_item_id=open_item.id,payment_movement_id=payment.id).first()
            if existing:existing.matched_amount=money(existing.matched_amount)+amount;existing.match_rule="manual selection";existing.confidence=100
            else:session.add(OpenItemMatch(open_item_id=open_item.id,payment_movement_id=payment.id,matched_amount=amount,match_rule="manual selection",confidence=100))
            total+=amount
        open_item.matched_amount=money(open_item.matched_amount)+total;open_item.remaining_amount=money(open_item.original_amount)-money(open_item.matched_amount);open_item.status="Fazla Ödeme" if open_item.remaining_amount<0 else "Tam Kapandı" if open_item.remaining_amount==0 else "Kısmen Kapandı";CurrentAccountAudit.log(session,"OPEN_ITEM_MATCHED","open_item",open_item.id,None,{"manual":True,"amount":str(total)});session.commit()


class AccountAnalyticsService:
    BUCKETS=((0,7,"0–7 gün"),(8,15,"8–15 gün"),(16,30,"16–30 gün"),(31,60,"31–60 gün"),(61,90,"61–90 gün"),(91,99999,"90+ gün"))
    @classmethod
    def aging(cls,session,account_id=None,today=None):
        today=today or datetime.utcnow().date();query=session.query(OpenItem).filter(OpenItem.remaining_amount>0);query=query.filter_by(account_id=account_id) if account_id else query;result={label:ZERO for _,_,label in cls.BUCKETS}
        for item in query.all():
            days=max((today-(item.due_date or datetime.combine(today,datetime.min.time())).date()).days,0)
            for low,high,label in cls.BUCKETS:
                if low<=days<=high:result[label]+=money(item.remaining_amount);break
        return {key:money(value) for key,value in result.items()}

    @staticmethod
    def payment_behavior(session,account_id,today=None):
        today=today or datetime.utcnow().date();delays=[];closed=session.query(OpenItem).filter_by(account_id=account_id,status="Tam Kapandı").all()
        for item in closed:
            last=session.query(OpenItemMatch).filter_by(open_item_id=item.id).order_by(OpenItemMatch.created_at.desc()).first()
            if last and item.due_date:
                payment=session.get(CurrentAccountMovement,last.payment_movement_id);delays.append((payment.transaction_date.date()-item.due_date.date()).days)
        open_items=session.query(OpenItem).filter_by(account_id=account_id).all();balances=[money(x.remaining_amount) for x in open_items];return {"average_payment_delay":money(sum(delays)/len(delays)) if delays else ZERO,"median_payment_delay":money(median(delays)) if delays else ZERO,"on_time_payment_rate":money(sum(1 for x in delays if x<=0)/len(delays)*100) if delays else ZERO,"overdue_invoice_count":sum(1 for x in open_items if x.remaining_amount>0 and x.due_date and x.due_date.date()<today),"average_open_balance":money(sum(balances,ZERO)/len(balances)) if balances else ZERO,"maximum_open_balance":max(balances,default=ZERO),"payment_frequency":len(delays)}

    @classmethod
    def risk(cls,session,account,today=None):
        today=today or datetime.utcnow().date();open_items=session.query(OpenItem).filter(OpenItem.account_id==account.id,OpenItem.remaining_amount>0).all();overdue=sum((money(x.remaining_amount) for x in open_items if x.due_date and x.due_date.date()<today),ZERO);max_days=max([(today-x.due_date.date()).days for x in open_items if x.due_date and x.due_date.date()<today] or [0]);unmatched=session.query(CurrentAccountMovement).filter_by(account_id=account.id,status="Eşleşmeyen").count();disputes=session.query(AccountReconciliation).filter_by(account_id=account.id,status="Mutabık Değil").count();score=min(100,float(min(overdue/Decimal("250"),40)+min(Decimal(max_days)/3,30)+unmatched*10+disputes*20));level="Yüksek" if score>=60 else "Orta" if score>=30 else "Düşük";components={"overdue_amount":str(money(overdue)),"maximum_overdue_days":max_days,"unmatched":unmatched,"disputes":disputes};explanation=f"Gecikmiş bakiye {money(overdue)}, azami gecikme {max_days} gün, eşleşmeyen {unmatched}, ihtilaflı mutabakat {disputes}.";return money(score),level,components,explanation


class AutomaticAccountReconciliationService:
    @staticmethod
    def create(session,account,start,end,currency,notes=None):
        start_dt=start if isinstance(start,datetime) else datetime.combine(start,datetime.min.time());end_dt=end if isinstance(end,datetime) else datetime.combine(end,datetime.max.time());all_rows=session.query(CurrentAccountMovement).filter(CurrentAccountMovement.account_id==account.id,CurrentAccountMovement.currency==currency,CurrentAccountMovement.transaction_date<=end_dt).order_by(CurrentAccountMovement.transaction_date,CurrentAccountMovement.id).all();opening=sum((money(x.debit)-money(x.credit) for x in all_rows if x.transaction_date<start_dt),ZERO);period=[x for x in all_rows if start_dt<=x.transaction_date<=end_dt];debits=sum((money(x.debit) for x in period),ZERO);credits=sum((money(x.credit) for x in period),ZERO);snapshot=hashlib.sha256("|".join(x.source_hash for x in all_rows).encode()).hexdigest();row=AccountReconciliation(account_id=account.id,reference_number=f"CM-{account.id}-{datetime.utcnow():%Y%m%d%H%M%S%f}",period_start=start_dt,period_end=end_dt,currency=currency,opening_balance=money(opening),debit_total=money(debits),credit_total=money(credits),closing_balance=money(opening+debits-credits),source_snapshot_hash=snapshot,notes=notes);session.add(row);session.flush();AutomaticAccountReconciliationService.detect_differences(session,row);CurrentAccountAudit.log(session,"RECONCILIATION_CREATED","account_reconciliation",row.id,None,{"closing_balance":str(row.closing_balance)});session.commit();return row

    @staticmethod
    def detect_differences(session,reconciliation):
        items=session.query(OpenItem).filter_by(account_id=reconciliation.account_id).all()
        invoice_numbers={}
        for item in items:
            if item.invoice_number in invoice_numbers and item.invoice_number:session.add(AccountReconciliationDifference(reconciliation_id=reconciliation.id,difference_type="duplicate invoice",severity="Kritik",amount=item.original_amount,currency=item.currency,source_type="open_item",source_id=item.id,explanation="Aynı fatura numarası birden fazla açık kalemde bulundu."))
            invoice_numbers[item.invoice_number]=item.id
            if item.status=="Fazla Ödeme":session.add(AccountReconciliationDifference(reconciliation_id=reconciliation.id,difference_type="payment greater than invoice",severity="Kritik",amount=abs(item.remaining_amount),currency=item.currency,source_type="open_item",source_id=item.id,explanation="Eşleşen ödeme fatura tutarını aşıyor."))
        unmatched=session.query(CurrentAccountMovement).filter_by(account_id=reconciliation.account_id,status="Eşleşmeyen").all()
        for movement in unmatched:session.add(AccountReconciliationDifference(reconciliation_id=reconciliation.id,difference_type="bank movement not linked",severity="Kontrol Gerekli",amount=abs(money(movement.debit)-money(movement.credit)),currency=movement.currency,source_type=movement.source_type,source_id=movement.source_id,explanation="Banka hareketi açık bir fatura ile eşleşmedi."))

    @staticmethod
    def lock(session,reconciliation):
        reconciliation.lock_status="Kilitli";reconciliation.status="Kontrol Edildi";reconciliation.finalized_at=datetime.utcnow();CurrentAccountAudit.log(session,"PERIOD_LOCKED","account_reconciliation",reconciliation.id);CurrentAccountAudit.log(session,"RECONCILIATION_FINALIZED","account_reconciliation",reconciliation.id);session.commit()
    @staticmethod
    def reopen(session,reconciliation):reconciliation.lock_status="Yeniden Açıldı";reconciliation.reopened_at=datetime.utcnow();CurrentAccountAudit.log(session,"PERIOD_REOPENED","account_reconciliation",reconciliation.id);session.commit()
    @staticmethod
    def record_response(session,reconciliation,status,counterparty_balance=None,explanation=None,follow_up=None,attachment=None):
        if status=="Mutabık Değil" and (counterparty_balance is None or not explanation):raise ValueError("Mutabık değil yanıtında karşı taraf bakiyesi ve açıklama zorunludur.")
        document_id=None
        if attachment:
            document,_=store_document_bytes(attachment[0],attachment[1],attachment[2],session,commit=False);document_id=document.id
        difference=money(counterparty_balance)-money(reconciliation.closing_balance) if counterparty_balance is not None else None;response=AccountReconciliationResponse(reconciliation_id=reconciliation.id,response_status=status,counterparty_balance=counterparty_balance,difference_amount=difference,explanation=explanation,document_id=document_id,follow_up_note=follow_up);session.add(response);reconciliation.status=status;session.flush();CurrentAccountAudit.log(session,"RECONCILIATION_RESPONSE_RECORDED","account_reconciliation",reconciliation.id,None,{"status":status});
        if status=="Mutabık Değil":session.add(AccountReconciliationDifference(reconciliation_id=reconciliation.id,difference_type="counterparty reported balance",severity="Kritik",amount=abs(difference),currency=reconciliation.currency,explanation=explanation,status="Açık"));CurrentAccountAudit.log(session,"RECONCILIATION_DISPUTED","account_reconciliation",reconciliation.id)
        session.commit();return response
    @staticmethod
    def draft(account,reconciliation,language="TR"):
        if language=="EN":return f"As of {reconciliation.period_end:%d.%m.%Y}, our records show a balance of {reconciliation.closing_balance} {reconciliation.currency} for {account.name}. Please compare it with your records and confirm the reconciliation status."
        return f"{reconciliation.period_end:%d.%m.%Y} tarihi itibarıyla kayıtlarımızda {account.name} hesabı {reconciliation.closing_balance} {reconciliation.currency} bakiye göstermektedir. Kayıtlarınızla karşılaştırarak mutabakat durumunu bildirmenizi rica ederiz."
    @staticmethod
    def exports(session,reconciliation,company_title="Seyahat Acentası"):
        account=session.get(CurrentAccount,reconciliation.account_id);items=session.query(OpenItem).filter_by(account_id=account.id).all();rows=[{"Şirket":company_title,"Cari":account.name,"Referans":reconciliation.reference_number,"Dönem":f"{reconciliation.period_start:%d.%m.%Y} - {reconciliation.period_end:%d.%m.%Y}","Açılış":reconciliation.opening_balance,"Borç":reconciliation.debit_total,"Alacak":reconciliation.credit_total,"Kapanış":reconciliation.closing_balance,"Açık Fatura":item.invoice_number,"Açık Tutar":item.remaining_amount,"Döviz":item.currency} for item in items] or [{"Şirket":company_title,"Cari":account.name,"Referans":reconciliation.reference_number,"Açılış":reconciliation.opening_balance,"Borç":reconciliation.debit_total,"Alacak":reconciliation.credit_total,"Kapanış":reconciliation.closing_balance}];return ReconciliationExportService.excel(rows,"Cari Mutabakat"),ReconciliationExportService.pdf(rows,"Cari Hesap Mutabakat Formu")


class ExchangeDifferenceService:
    @staticmethod
    def calculate(session,invoice,payment,amount):
        invoice_base=money(amount*invoice.exchange_rate);payment_base=money(amount*payment.exchange_rate);difference=money(payment_base-invoice_base);existing=session.query(ExchangeDifferenceEntry).filter_by(invoice_movement_id=invoice.id,payment_movement_id=payment.id).first()
        if existing:return existing,True
        row=ExchangeDifferenceEntry(account_id=invoice.account_id,invoice_movement_id=invoice.id,payment_movement_id=payment.id,original_amount=money(amount),currency=invoice.currency,invoice_rate=invoice.exchange_rate,payment_rate=payment.exchange_rate,invoice_base_value=invoice_base,payment_base_value=payment_base,difference_amount=difference,classification="Kazanç" if difference>0 else "Kayıp" if difference<0 else "Fark Yok",approval_status="Onay Bekliyor");session.add(row);session.flush();CurrentAccountAudit.log(session,"EXCHANGE_DIFFERENCE_CALCULATED","exchange_difference_entry",row.id,None,{"difference":str(difference)});session.commit();return row,False


class DailyCurrentAccountService:
    @staticmethod
    def refresh(session,today=None):
        created=CurrentAccountProjectionService.rebuild(session);matches=OpenItemMatchingService.rebuild_open_items(session)
        score_date=datetime.combine(today or datetime.utcnow().date(),datetime.min.time());risks=0
        for account in session.query(CurrentAccount).all():
            score,level,components,explanation=AccountAnalyticsService.risk(session,account,score_date.date());existing=session.query(AccountRiskScore).filter_by(account_id=account.id,score_date=score_date).first()
            if existing:existing.score,existing.risk_level,existing.components,existing.explanation=score,level,components,explanation
            else:session.add(AccountRiskScore(account_id=account.id,score_date=score_date,score=score,risk_level=level,components=components,explanation=explanation));risks+=1
        session.commit();return {"movements_created":created,"matches_created":matches,"risks_created":risks}
