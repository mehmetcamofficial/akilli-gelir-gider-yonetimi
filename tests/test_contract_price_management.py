from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, ContractDocument, ContractPriceRule, Notification, Supplier, Tour
from services.business_value_service import ContractManagementService, ContractPriceService


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); engine=create_engine(f"sqlite:///{tmp_path/'contracts.db'}"); Base.metadata.create_all(engine); db=sessionmaker(bind=engine)(); yield db; db.close(); engine.dispose()


def contract(session, supplier, kind, start, end, title="Agreement"):
    row, version=ContractManagementService.create_contract(session,supplier.id,kind,title,start,end,"EUR")
    return row,version


def test_restaurant_historical_lookup_free_rules_and_child_pricing(session):
    supplier=Supplier(name="Restaurant A"); session.add(supplier); session.flush(); start=datetime(2026,1,1); end=datetime(2026,12,31); row,version=contract(session,supplier,"Restoran",start,end,"Summer")
    ContractManagementService.create_price_rule(session,row,version,"Restoran","Lunch",start,datetime(2026,6,30,23,59),"Kişi Başı",adult_price=20,child_price=10,subtype_values={"meal_type":"Lunch","menu_name":"A","guide_price":10,"driver_price":10,"free_guide":True,"free_driver":True,"free_person_ratio":20,"additional_service_price":0,"minimum_passenger_count":0,"group_price":0})
    ContractManagementService.create_price_rule(session,row,version,"Restoran","Dinner",datetime(2026,7,1),end,"Kişi Başı",adult_price=22,child_price=11,subtype_values={"meal_type":"Dinner","menu_name":"B","guide_price":0,"driver_price":0,"free_guide":True,"free_driver":True,"free_person_ratio":20,"additional_service_price":0,"minimum_passenger_count":0,"group_price":0}); session.commit()
    june=ContractPriceService.find_valid_price(session,supplier.id,"Restoran",datetime(2026,6,15),selectors={"meal_type":"Lunch"}); august=ContractPriceService.find_valid_price(session,supplier.id,"Restoran",datetime(2026,8,15),selectors={"meal_type":"Dinner"})
    assert june["rule"].adult_price==20 and august["rule"].adult_price==22
    result=ContractPriceService.calculate_expected_price(june,adults=21,children=2,guide_count=1,driver_count=1)
    assert result["expected_amount"]==Decimal("420.00")


def test_hotel_seasonal_transfer_route_and_guide_language(session):
    supplier=Supplier(name="Mixed"); session.add(supplier); session.flush(); start=datetime(2026,1,1); end=datetime(2026,12,31)
    for kind, subtype in [
        ("Otel",{"room_type":"double","board_type":"BB","double_room":100,"city_tax":5}),
        ("Transfer",{"origin":"ADB","destination":"Kusadasi","vehicle_type":"Minibus","passenger_capacity":16,"one_way_price":150,"round_trip_price":280,"waiting_hour_price":10,"extra_kilometer_price":2,"airport_fee":20,"night_surcharge":30,"driver_accommodation":0}),
        ("Rehber",{"language":"English","service_type":"Tam Gün","half_day_price":80,"full_day_price":140,"hourly_overtime":20,"overnight_allowance":0,"meal_allowance":10,"transportation_allowance":5,"museum_fee":0}),
    ]:
        row,version=contract(session,supplier,kind,start,end,kind); ContractManagementService.create_price_rule(session,row,version,kind,kind,start,end,"Oda / Gece" if kind=="Otel" else "Tek Yön",base_price=100,subtype_values=subtype)
    session.commit()
    hotel=ContractPriceService.find_valid_price(session,supplier.id,"Otel",datetime(2026,7,1),selectors={"room_type":"double","board_type":"BB"}); assert ContractPriceService.calculate_expected_price(hotel,rooms=2,nights=3,room_type="double")["expected_amount"]==Decimal("630.00")
    transfer=ContractPriceService.find_valid_price(session,supplier.id,"Transfer",datetime(2026,7,1),selectors={"origin":"ADB","destination":"Kusadasi","vehicle_type":"Minibus"}); assert ContractPriceService.calculate_expected_price(transfer,round_trip=True,waiting_hours=2)["expected_amount"]==Decimal("320.00")
    guide=ContractPriceService.find_valid_price(session,supplier.id,"Rehber",datetime(2026,7,1),selectors={"language":"English"}); assert ContractPriceService.calculate_expected_price(guide,duration="Tam Gün",overtime_hours=2)["expected_amount"]==Decimal("195.00")


def test_overlap_prevention_and_tour_specific_override(session):
    supplier=Supplier(name="S"); tour=Tour(code="T",name="Pamukkale"); session.add_all([supplier,tour]); session.flush(); start=datetime(2026,1,1); end=datetime(2026,12,31)
    generic,vg=contract(session,supplier,"Restoran",start,end,"Generic"); ContractManagementService.create_price_rule(session,generic,vg,"Restoran","Lunch",start,end,"Kişi Başı",adult_price=20)
    with pytest.raises(ValueError): ContractManagementService.create_price_rule(session,generic,vg,"Restoran","Duplicate",start,end,"Kişi Başı",adult_price=21)
    session.rollback()
    # rollback removed the uncommitted setup; recreate and commit before adding override
    session.add_all([supplier,tour]); session.commit(); generic,vg=contract(session,supplier,"Restoran",start,end,"Generic"); ContractManagementService.create_price_rule(session,generic,vg,"Restoran","Lunch",start,end,"Kişi Başı",adult_price=20); session.commit()
    specific,vs=contract(session,supplier,"Restoran",start,end,"Tour"); ContractManagementService.create_price_rule(session,specific,vs,"Restoran","Lunch Tour",start,end,"Kişi Başı",adult_price=18,tour_id=tour.id); session.commit()
    match=ContractPriceService.find_valid_price(session,supplier.id,"Restoran",datetime(2026,6,1),tour_id=tour.id); assert match["rule"].adult_price==18 and match["priority"]==3


def test_fixed_group_difference_document_and_expiry(session):
    supplier=Supplier(name="Boat"); session.add(supplier); session.flush(); start=datetime(2026,1,1); end=datetime(2026,8,22); row,version=contract(session,supplier,"Tekne",start,end,"Boat"); rule=ContractManagementService.create_price_rule(session,row,version,"Tekne","Cruise",start,end,"Sabit Grup",base_price=500); session.commit()
    match=ContractPriceService.find_valid_price(session,supplier.id,"Tekne",datetime(2026,8,1)); assert ContractPriceService.calculate_expected_price(match,quantity=50)["expected_amount"]==Decimal("500.00")
    diff=ContractPriceService.price_difference(600,660); assert diff["status"]=="Fiyat Aşımı" and diff["potential_overpayment"]==Decimal("60.00")
    link=ContractManagementService.store_document(session,row,version,b"%PDF-1.4 contract","contract.pdf","application/pdf"); session.commit(); session.expire_all(); assert session.get(ContractDocument,link.id).file_hash
    assert ContractManagementService.create_expiry_notifications(session,datetime(2026,8,7).date())==1; assert session.query(Notification).filter_by(notification_type="contract_expiry").count()==1


def test_price_version_benchmark_simulation_and_excel_import(session):
    s1=Supplier(name="A"); s2=Supplier(name="B"); tour=Tour(code="E",name="Ephesus"); session.add_all([s1,s2,tour]); session.flush(); start=datetime(2026,1,1); end=datetime(2026,12,31)
    for supplier,price in [(s1,18),(s2,22)]:
        row,version=contract(session,supplier,"Restoran",start,end,supplier.name); rule=ContractManagementService.create_price_rule(session,row,version,"Restoran","Lunch",start,end,"Kişi Başı",adult_price=price)
    session.commit(); benchmark=ContractManagementService.benchmark(session,"Restoran","Lunch",datetime(2026,6,1)); assert {x["median"] for x in benchmark}=={Decimal("20.00")}
    rule=session.query(ContractPriceRule).filter_by(service_name="Lunch").first(); new=ContractManagementService.version_price(session,rule,20,datetime(2026,7,1)); session.commit(); assert rule.valid_until<new.valid_from
    simulation=ContractManagementService.simulate(session,tour.id,datetime(2026,8,1),10,0,0,"Bus","English",300); assert simulation["total_supplier_cost"]>0 and simulation["estimated_gross_profit"]<300
    imported=ContractManagementService.import_rows(session,[{"supplier":"A","contract_type":"Diğer tedarikçi","service":"Museum","valid_from":"2027-01-01T00:00:00","valid_until":"2027-12-31T00:00:00","currency":"EUR","adult_price":15}]); assert imported==1
