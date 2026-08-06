from .models import (
    Base,
    Category,
    Transaction,
    SalesChannel,
    Staff,
    Supplier,
    Customer,
    Tour,
    Booking,
    Hotel,
    HotelBooking,
    Collection,
    SupplierPayment,
    Passenger,
    BookingService,
    TourDeparture,
    TourCostItem,
    Transfer,
    GuideAssignment,
    Cancellation,
    Refund,
    Voucher,
    Transaction,
    Document,
    InvoiceItem,
)
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime, timedelta
from decimal import Decimal
import random


DEMO_TOUR_CODES = ["KUS-001", "PAM-001"]
DEMO_BOOKING_NUMBERS = ["BK-2026-0001", "BK-2026-0002"]
DEMO_CUSTOMER_EMAILS = ["john.doe@example.com", "fatma.celik@example.com"]
DEMO_SUPPLIER_NAMES = ["Kuşadası Otel A.Ş.", "Ege Transfer", "Efes Rehberlik"]
DEMO_STAFF_EMAILS = ["ayse@acenta.com", "murat@acenta.com", "deniz@acenta.com"]
DEMO_SALES_CHANNEL_NAMES = ["Ofis satışı", "Web sitesi", "WhatsApp", "Telefon", "Alt acenta"]
DEMO_COLLECTION_REFS = ["TRX12345", "TRX54321"]
DEMO_SUPPLIER_INVOICE_REFS = ["SUP-001"]


def seed_demo_data(force=False):
    # import engine lazily to avoid circular imports
    from .db import engine
    Session = sessionmaker(bind=engine)
    session = Session()

    if not force and session.query(Tour).filter(Tour.code.in_(DEMO_TOUR_CODES)).count() > 0:
        session.close()
        return

    # create sales channels
    office = SalesChannel(name="Ofis satışı", is_demo=True)
    web = SalesChannel(name="Web sitesi", is_demo=True)
    whatsapp = SalesChannel(name="WhatsApp", is_demo=True)
    phone = SalesChannel(name="Telefon", is_demo=True)
    supplier = SalesChannel(name="Alt acenta", is_demo=True)
    session.add_all([office, web, whatsapp, phone, supplier])

    # create staff
    sales1 = Staff(first_name="Ayşe", last_name="Yılmaz", role="Satış", phone="0555 111 2233", email="ayse@acenta.com", is_demo=True)
    sales2 = Staff(first_name="Murat", last_name="Demir", role="Satış", phone="0555 222 3344", email="murat@acenta.com", is_demo=True)
    ops = Staff(first_name="Deniz", last_name="Kaya", role="Operasyon", phone="0555 333 4455", email="deniz@acenta.com", is_demo=True)
    session.add_all([sales1, sales2, ops])

    # create suppliers
    hotel1 = Supplier(name="Kuşadası Otel A.Ş.", supplier_type="Otel", contact_person="Selin", tax_office="Kuşadası", tax_number="1234567890", phone="0256 123 4567", email="hotel@example.com", currency="TRY", is_demo=True)
    transfer1 = Supplier(name="Ege Transfer", supplier_type="Transfer firması", contact_person="Emre", currency="TRY", phone="0256 765 4321", is_demo=True)
    guide1 = Supplier(name="Efes Rehberlik", supplier_type="Rehber", contact_person="Aslı", currency="TRY", phone="0256 444 5566", is_demo=True)
    session.add_all([hotel1, transfer1, guide1])

    # create customers
    customer1 = Customer(first_name="John", last_name="Doe", nationality="USA", phone="+1 555 123 4567", email="john.doe@example.com", address="123 Main St", billing_info="John Doe, 123 Main St", tax_number="US123456", is_demo=True)
    customer2 = Customer(first_name="Fatma", last_name="Çelik", nationality="Turkey", phone="+90 532 111 2233", email="fatma.celik@example.com", address="İzmir", billing_info="Fatma Çelik, İzmir", tax_number="TR987654", is_demo=True)
    session.add_all([customer1, customer2])

    # create tours
    tour1 = Tour(code="KUS-001", name="Kuşadası Günlük Kültür Turu", tour_type="Günlük kültür turu", start_location="Kuşadası", end_location="Kuşadası", duration_days=1, departure_datetime=datetime.utcnow() + timedelta(days=7), return_datetime=datetime.utcnow() + timedelta(days=7, hours=8), capacity=30, min_participants=5, adult_price=Decimal('1250.00'), child_price=Decimal('950.00'), infant_price=Decimal('450.00'), currency="TRY", default_guide="Aslı", default_vehicle="Minibüs", included_services="Rehberlik, öğle yemeği, müze girişleri", excluded_services="Kişisel harcamalar", cancellation_policy="48 saat öncesine kadar ücretsiz iptal.", status="Satışta", is_demo=True)
    tour2 = Tour(code="PAM-001", name="Pamukkale & Hierapolis Turu", tour_type="Doğa turu", start_location="Kuşadası", end_location="Kuşadası", duration_days=1, departure_datetime=datetime.utcnow() + timedelta(days=14), return_datetime=datetime.utcnow() + timedelta(days=14, hours=10), capacity=28, min_participants=6, adult_price=Decimal('1380.00'), child_price=Decimal('1080.00'), infant_price=Decimal('520.00'), currency="TRY", default_guide="Emre", default_vehicle="Tur otobüsü", included_services="Rehberlik, öğle yemeği, giriş ücretleri", excluded_services="İçecekler", cancellation_policy="72 saat öncesine kadar ücretsiz iptal.", status="Satışta", is_demo=True)
    session.add_all([tour1, tour2])

    session.commit()

    # create bookings
    booking1 = Booking(
        booking_number="BK-2026-0001",
        booking_date=datetime.utcnow() - timedelta(days=5),
        service_start_date=datetime.utcnow() + timedelta(days=7),
        service_end_date=datetime.utcnow() + timedelta(days=7, hours=8),
        tour_id=tour1.id,
        booking_type="Günlük tur",
        customer_id=customer1.id,
        passenger_count=2,
        adult_count=2,
        child_count=0,
        infant_count=0,
        sales_channel_id=web.id,
        sales_person_id=sales1.id,
        guide_id=ops.id,
        currency="TRY",
        exchange_rate=Decimal('1.0'),
        unit_price=Decimal('1250.00'),
        total_price=Decimal('2500.00'),
        discount_amount=Decimal('0.00'),
        commission_amount=Decimal('250.00'),
        tax_amount=Decimal('450.00'),
        grand_total=Decimal('2950.00'),
        deposit_amount=Decimal('1000.00'),
        collected_total=Decimal('1000.00'),
        remaining_amount=Decimal('1950.00'),
        payment_method="Kredi kartı",
        final_payment_date=datetime.utcnow() + timedelta(days=3),
        booking_status="Kısmen ödendi",
        operation_status="Planlandı",
        voucher_number="VCH-0001",
        notes="Yabancı müşteri için transfer dahil.",
        is_demo=True,
    )

    booking2 = Booking(
        booking_number="BK-2026-0002",
        booking_date=datetime.utcnow() - timedelta(days=10),
        service_start_date=datetime.utcnow() + timedelta(days=14),
        service_end_date=datetime.utcnow() + timedelta(days=14, hours=10),
        tour_id=tour2.id,
        booking_type="Paket tur",
        customer_id=customer2.id,
        passenger_count=4,
        adult_count=2,
        child_count=2,
        infant_count=0,
        sales_channel_id=office.id,
        sales_person_id=sales2.id,
        guide_id=ops.id,
        currency="TRY",
        exchange_rate=Decimal('1.0'),
        unit_price=Decimal('1380.00'),
        total_price=Decimal('5520.00'),
        discount_amount=Decimal('200.00'),
        commission_amount=Decimal('300.00'),
        tax_amount=Decimal('540.00'),
        grand_total=Decimal('5860.00'),
        deposit_amount=Decimal('2000.00'),
        collected_total=Decimal('2000.00'),
        remaining_amount=Decimal('3860.00'),
        payment_method="Banka havalesi",
        final_payment_date=datetime.utcnow() + timedelta(days=5),
        booking_status="Kısmen ödendi",
        operation_status="Tedarikçiler onaylanıyor",
        voucher_number="VCH-0002",
        notes="Pamukkale turu için otel rezervasyonu yapıldı.",
        is_demo=True,
    )

    session.add_all([booking1, booking2])
    session.commit()

    # create hotel bookings
    hotel_booking1 = HotelBooking(
        booking_id=booking2.id,
        hotel_id=hotel1.id,
        checkin_date=datetime.utcnow() + timedelta(days=14),
        checkout_date=datetime.utcnow() + timedelta(days=15),
        nights=1,
        room_count=2,
        room_type="Standart",
        board_type="Sadece oda",
        adult_count=2,
        child_count=2,
        price_per_room=Decimal('950.00'),
        price_per_person=Decimal('475.00'),
        extra_bed=Decimal('150.00'),
        discount_amount=Decimal('100.00'),
        tax_amount=Decimal('90.00'),
        total_cost=Decimal('1970.00'),
        cancellation_policy="72 saat öncesine kadar ücretsiz iptal.",
        free_cancellation_until=datetime.utcnow() + timedelta(days=11),
        is_demo=True,
    )

    session.add(hotel_booking1)
    session.commit()

    # create collections
    collection1 = Collection(
        booking_id=booking1.id,
        customer_id=customer1.id,
        collection_date=datetime.utcnow() - timedelta(days=5),
        amount=Decimal('1000.00'),
        currency="TRY",
        exchange_rate=Decimal('1.0'),
        amount_in_tl=Decimal('1000.00'),
        payment_method="Kredi kartı",
        account_name="Kasa",
        transaction_reference="TRX12345",
        receipt_number="RCP12345",
        staff_id=sales1.id,
        notes="Kapora tahsilatı.",
        is_demo=True,
    )

    collection2 = Collection(
        booking_id=booking2.id,
        customer_id=customer2.id,
        collection_date=datetime.utcnow() - timedelta(days=9),
        amount=Decimal('2000.00'),
        currency="TRY",
        exchange_rate=Decimal('1.0'),
        amount_in_tl=Decimal('2000.00'),
        payment_method="Banka havalesi",
        account_name="Banka",
        transaction_reference="TRX54321",
        receipt_number="RCP54321",
        staff_id=sales2.id,
        notes="İlk kapora tahsilatı.",
        is_demo=True,
    )

    session.add_all([collection1, collection2])

    # create supplier payments
    supplier_payment1 = SupplierPayment(
        supplier_id=hotel1.id,
        booking_id=booking2.id,
        invoice_reference="SUP-001",
        service_date=datetime.utcnow() + timedelta(days=14),
        due_date=datetime.utcnow() + timedelta(days=20),
        total_debt=Decimal('1970.00'),
        paid_amount=Decimal('0.00'),
        remaining_amount=Decimal('1970.00'),
        currency="TRY",
        exchange_rate=Decimal('1.0'),
        payment_method="EFT",
        account_name="Banka",
        payment_status="Beklemede",
        notes="Otel ödeme bekleniyor.",
        is_demo=True,
    )

    session.add(supplier_payment1)

    session.commit()
    session.close()


def delete_demo_data():
    from .db import engine
    Session = sessionmaker(bind=engine)
    session = Session()

    deleted = {
        "bookings": 0,
        "tours": 0,
        "customers": 0,
        "suppliers": 0,
        "transactions": 0,
        "invoices": 0,
        "collections": 0,
        "supplier_payments": 0,
        "documents": 0,
    }
    try:
        booking_ids = [row[0] for row in session.query(Booking.id).filter(Booking.is_demo.is_(True))]
        tour_ids = [row[0] for row in session.query(Tour.id).filter(Tour.is_demo.is_(True))]
        transaction_ids = [row[0] for row in session.query(Transaction.id).filter(Transaction.is_demo.is_(True))]
        deleted["invoices"] = session.query(Transaction).filter(
            Transaction.id.in_(transaction_ids),
            Transaction.invoice_number.isnot(None),
            Transaction.invoice_number != "",
        ).count() if transaction_ids else 0

        if booking_ids:
            for model in (Passenger, BookingService, HotelBooking, GuideAssignment, Transfer,
                          Cancellation, Refund, Voucher):
                session.query(model).filter(model.booking_id.in_(booking_ids)).delete(synchronize_session=False)
            deleted["collections"] += session.query(Collection).filter(
                Collection.booking_id.in_(booking_ids)
            ).delete(synchronize_session=False)
            deleted["supplier_payments"] += session.query(SupplierPayment).filter(
                SupplierPayment.booking_id.in_(booking_ids)
            ).delete(synchronize_session=False)
            deleted["bookings"] = session.query(Booking).filter(
                Booking.id.in_(booking_ids)
            ).delete(synchronize_session=False)

        if tour_ids:
            for model in (TourDeparture, TourCostItem, GuideAssignment, Transfer):
                session.query(model).filter(model.tour_id.in_(tour_ids)).delete(synchronize_session=False)
            deleted["supplier_payments"] += session.query(SupplierPayment).filter(
                SupplierPayment.tour_id.in_(tour_ids)
            ).delete(synchronize_session=False)
            deleted["tours"] = session.query(Tour).filter(Tour.id.in_(tour_ids)).delete(
                synchronize_session=False
            )

        if transaction_ids:
            deleted["documents"] += session.query(Document).filter(
                Document.transaction_id.in_(transaction_ids)
            ).delete(synchronize_session=False)
            session.query(InvoiceItem).filter(InvoiceItem.invoice_id.in_(transaction_ids)).delete(
                synchronize_session=False
            )
            deleted["transactions"] = session.query(Transaction).filter(
                Transaction.id.in_(transaction_ids)
            ).delete(synchronize_session=False)

        deleted["documents"] += session.query(Document).filter(Document.is_demo.is_(True)).delete(
            synchronize_session=False
        )
        deleted["collections"] += session.query(Collection).filter(
            Collection.is_demo.is_(True)
        ).delete(synchronize_session=False)
        deleted["supplier_payments"] += session.query(SupplierPayment).filter(
            SupplierPayment.is_demo.is_(True)
        ).delete(synchronize_session=False)
        deleted["customers"] = session.query(Customer).filter(Customer.is_demo.is_(True)).delete(
            synchronize_session=False
        )
        deleted["suppliers"] = session.query(Supplier).filter(Supplier.is_demo.is_(True)).delete(
            synchronize_session=False
        )
        session.query(Staff).filter(Staff.is_demo.is_(True)).delete(synchronize_session=False)
        session.query(SalesChannel).filter(SalesChannel.is_demo.is_(True)).delete(
            synchronize_session=False
        )
        session.flush()
        remaining = sum(
            session.query(model).filter(model.is_demo.is_(True)).count()
            for model in (
                Booking, Tour, Customer, Supplier, Transaction, Collection,
                SupplierPayment, Document, Staff, SalesChannel, HotelBooking,
            )
        )
        if remaining:
            raise RuntimeError(f"{remaining} demo kaydı silinemedi; işlem geri alındı.")
        session.commit()
        return deleted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def restore_demo_data():
    delete_demo_data()
    seed_demo_data(force=True)


def init_and_seed():
    from .db import engine
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    mark_legacy_demo_data()


def migrate_schema():
    """Additive legacy migration used by local SQLite fallback databases."""
    from .db import engine

    additions = {
        "transactions": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "documents": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "sales_channels": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "staff": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "customers": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "tours": [
            ("status", "VARCHAR(100) DEFAULT 'Taslak'"),
            ("is_demo", "BOOLEAN NOT NULL DEFAULT 0"),
            ("created_at", "DATETIME"),
            ("updated_at", "DATETIME"),
        ],
        "bookings": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "hotel_bookings": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "collections": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "suppliers": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
        "supplier_payments": [("is_demo", "BOOLEAN NOT NULL DEFAULT 0")],
    }
    with engine.begin() as connection:
        existing_tables = set(inspect(connection).get_table_names())
        for table, columns in additions.items():
            if table not in existing_tables:
                continue
            existing_columns = {col["name"] for col in inspect(connection).get_columns(table)}
            for name, definition in columns:
                if name not in existing_columns:
                    connection.exec_driver_sql(
                        f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'
                    )


def mark_legacy_demo_data():
    """Mark demo rows created by older versions before `is_demo` existed."""
    from .db import engine

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE tours SET is_demo = 1 WHERE code IN ('KUS-001', 'PAM-001')"
        )
        connection.exec_driver_sql(
            "UPDATE bookings SET is_demo = 1 WHERE booking_number IN ('BK-2026-0001', 'BK-2026-0002')"
        )
        connection.exec_driver_sql(
            "UPDATE customers SET is_demo = 1 WHERE email IN ('john.doe@example.com', 'fatma.celik@example.com')"
        )
        connection.exec_driver_sql(
            "UPDATE suppliers SET is_demo = 1 WHERE name IN ('Kuşadası Otel A.Ş.', 'Ege Transfer', 'Efes Rehberlik')"
        )
        connection.exec_driver_sql(
            "UPDATE staff SET is_demo = 1 WHERE email IN ('ayse@acenta.com', 'murat@acenta.com', 'deniz@acenta.com')"
        )
        connection.exec_driver_sql(
            "UPDATE sales_channels SET is_demo = 1 WHERE name IN ('Ofis satışı', 'Web sitesi', 'WhatsApp', 'Telefon', 'Alt acenta')"
        )
        connection.exec_driver_sql(
            "UPDATE collections SET is_demo = 1 WHERE transaction_reference IN ('TRX12345', 'TRX54321')"
        )
        connection.exec_driver_sql(
            "UPDATE supplier_payments SET is_demo = 1 WHERE invoice_reference = 'SUP-001'"
        )
        connection.exec_driver_sql(
            "UPDATE hotel_bookings SET is_demo = 1 WHERE booking_id IN (SELECT id FROM bookings WHERE is_demo = 1)"
        )
        connection.exec_driver_sql(
            "UPDATE transactions SET is_demo = 1 "
            "WHERE description LIKE 'Demo işlem %' AND invoice_number LIKE 'FAT-%'"
        )


def migrate_add_invoice_type():
    """Portable additive migration retained for old local installations."""
    from .db import engine
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("transactions")}
        if "invoice_type" not in columns:
            connection.exec_driver_sql("ALTER TABLE transactions ADD COLUMN invoice_type VARCHAR(20)")


if __name__ == "__main__":
    init_and_seed()
