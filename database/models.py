from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
from decimal import Decimal

Base = declarative_base()


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    children = relationship("Category")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    transaction_type = Column(String(20), nullable=False)  # income or expense
    invoice_type = Column(String(20), nullable=True)  # sale or purchase (optional)
    transaction_date = Column(DateTime, default=datetime.utcnow)
    document_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    invoice_number = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    party_name = Column(String(255), nullable=True)
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18, 6), default=Decimal("1.0"))
    subtotal = Column(Numeric(18, 2), default=Decimal("0.00"))
    tax_total = Column(Numeric(18, 2), default=Decimal("0.00"))
    discount_total = Column(Numeric(18, 2), default=Decimal("0.00"))
    grand_total = Column(Numeric(18, 2), default=Decimal("0.00"))
    paid_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    remaining_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    payment_status = Column(String(50), default="Ödenmedi")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    documents = relationship("Document", back_populates="transaction")
    items = relationship("InvoiceItem", back_populates="invoice")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    original_filename = Column(String(512))
    stored_filename = Column(String(512))
    file_path = Column(String(1024))
    file_type = Column(String(50))
    file_hash = Column(String(128), index=True)
    file_size = Column(Integer)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    transaction = relationship("Transaction", back_populates="documents")


class DocumentReconciliation(Base):
    __tablename__ = "document_reconciliations"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    document_hash = Column(String(128), nullable=False, index=True)
    extracted_json = Column(Text, nullable=False)
    matched_entity_type = Column(String(100), nullable=True)
    matched_entity_id = Column(Integer, nullable=True)
    status = Column(String(100), nullable=False)
    severity = Column(String(50), nullable=False)
    differences_json = Column(Text, nullable=False)
    expected_total = Column(Numeric(18, 2), nullable=True)
    document_total = Column(Numeric(18, 2), nullable=True)
    difference_amount = Column(Numeric(18, 2), nullable=True)
    difference_percentage = Column(Numeric(18, 4), nullable=True)
    recommended_action = Column(Text, nullable=True)
    user_action = Column(String(100), nullable=True)
    user_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)


class ReconciliationDocument(Base):
    __tablename__ = "reconciliation_documents"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=False, index=True)
    side = Column(String(20), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    source_type = Column(String(100), nullable=False)
    source_entity_type = Column(String(100), nullable=True)
    source_entity_id = Column(Integer, nullable=True)
    filename = Column(String(512), nullable=True)
    file_hash = Column(String(128), nullable=True, index=True)
    content_base64 = Column(Text, nullable=True)
    extracted_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ReconciliationField(Base):
    __tablename__ = "reconciliation_fields"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    incoming_value = Column(Text, nullable=True)
    agency_value = Column(Text, nullable=True)
    status = Column(String(100), nullable=False)
    explanation = Column(Text, nullable=True)


class ReconciliationDifference(Base):
    __tablename__ = "reconciliation_differences"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    incoming_value = Column(Text, nullable=True)
    agency_value = Column(Text, nullable=True)
    difference_value = Column(Text, nullable=True)
    severity = Column(String(50), nullable=False)
    explanation = Column(Text, nullable=True)


class ReconciliationApproval(Base):
    __tablename__ = "reconciliation_approvals"
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(Integer, ForeignKey("document_reconciliations.id"), nullable=False, index=True)
    action = Column(String(100), nullable=False)
    destination = Column(String(100), nullable=True)
    approved_by = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(Integer, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id = Column(Integer, primary_key=True)
    filename = Column(String(512), nullable=False)
    file_hash = Column(String(128), nullable=False, index=True)
    dataset_type = Column(String(100), nullable=False)
    total_rows = Column(Integer, default=0)
    imported_rows = Column(Integer, default=0)
    skipped_rows = Column(Integer, default=0)
    error_rows = Column(Integer, default=0)
    duplicate_rows = Column(Integer, default=0)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    id = Column(Integer, primary_key=True)
    transaction_date = Column(DateTime, nullable=True)
    description = Column(Text, nullable=True)
    reference_number = Column(String(255), nullable=True)
    amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    currency = Column(String(10), default="TRY")
    transaction_type = Column(String(20), nullable=True)
    import_batch_id = Column(Integer, ForeignKey("import_batches.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    product_id = Column(Integer, nullable=True)
    description = Column(String(500), nullable=True)
    quantity = Column(Numeric(18,4), default=Decimal('1.0'))
    unit = Column(String(50), nullable=True)
    unit_price = Column(Numeric(18,4), default=Decimal('0.00'))
    discount_rate = Column(Numeric(5,2), default=Decimal('0.00'))
    discount_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    tax_rate = Column(Numeric(5,2), default=Decimal('0.00'))
    tax_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    line_total = Column(Numeric(18,2), default=Decimal('0.00'))
    additional_cost = Column(Numeric(18,2), default=Decimal('0.00'))
    net_cost = Column(Numeric(18,2), default=Decimal('0.00'))
    invoice = relationship("Transaction", back_populates="items")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    code = Column(String(100), nullable=True)
    barcode = Column(String(100), nullable=True)
    name = Column(String(255), nullable=False)
    category = Column(String(200), nullable=True)
    brand = Column(String(200), nullable=True)
    unit = Column(String(50), default="ad")
    default_tax_rate = Column(Numeric(5,2), default=Decimal('18.00'))
    last_purchase_price = Column(Numeric(18,4), default=Decimal('0.00'))
    avg_purchase_price = Column(Numeric(18,4), default=Decimal('0.00'))
    last_sale_price = Column(Numeric(18,4), default=Decimal('0.00'))
    min_sale_price = Column(Numeric(18,4), default=Decimal('0.00'))
    stock = Column(Numeric(18,4), default=Decimal('0.00'))
    min_stock = Column(Numeric(18,4), default=Decimal('0.00'))
    is_active = Column(Boolean, default=True)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False)
    qty = Column(Numeric(18,4), default=Decimal('0.00'))
    movement_type = Column(String(50))  # 'in' or 'out'
    related_invoice_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SalesChannel(Base):
    __tablename__ = "sales_channels"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)


class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    role = Column(String(100), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    company_name = Column(String(255), nullable=True)
    nationality = Column(String(100), nullable=True)
    document_number = Column(String(200), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(Text, nullable=True)
    birth_date = Column(DateTime, nullable=True)
    language = Column(String(50), nullable=True)
    emergency_contact = Column(String(255), nullable=True)
    billing_info = Column(Text, nullable=True)
    tax_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    kvkk_confirmed = Column(Boolean, default=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    bookings = relationship("Booking", back_populates="customer")


class Passenger(Base):
    __tablename__ = "booking_passengers"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    nationality = Column(String(100), nullable=True)
    passport_number = Column(String(200), nullable=True)
    passport_expiry = Column(DateTime, nullable=True)
    birth_date = Column(DateTime, nullable=True)
    gender = Column(String(20), nullable=True)
    passenger_type = Column(String(50), nullable=True)
    room_type = Column(String(100), nullable=True)
    pickup_point = Column(String(255), nullable=True)
    meal_preference = Column(String(200), nullable=True)
    health_notes = Column(Text, nullable=True)
    special_request = Column(Text, nullable=True)
    booking = relationship("Booking", back_populates="passengers")


class Tour(Base):
    __tablename__ = "tours"
    id = Column(Integer, primary_key=True)
    code = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    tour_type = Column(String(100), nullable=True)
    start_location = Column(String(255), nullable=True)
    end_location = Column(String(255), nullable=True)
    duration_days = Column(Integer, nullable=True)
    departure_datetime = Column(DateTime, nullable=True)
    return_datetime = Column(DateTime, nullable=True)
    capacity = Column(Integer, nullable=True)
    min_participants = Column(Integer, nullable=True)
    adult_price = Column(Numeric(18,2), default=Decimal('0.00'))
    child_price = Column(Numeric(18,2), default=Decimal('0.00'))
    infant_price = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    default_guide = Column(String(255), nullable=True)
    default_vehicle = Column(String(255), nullable=True)
    included_services = Column(Text, nullable=True)
    excluded_services = Column(Text, nullable=True)
    cancellation_policy = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(100), default="Taslak")
    is_active = Column(Boolean, default=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    departures = relationship("TourDeparture", back_populates="tour")
    cost_items = relationship("TourCostItem", back_populates="tour")
    bookings = relationship("Booking", back_populates="tour")


class TourDeparture(Base):
    __tablename__ = "tour_departures"
    id = Column(Integer, primary_key=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=False)
    departure_datetime = Column(DateTime, nullable=True)
    return_datetime = Column(DateTime, nullable=True)
    seats_available = Column(Integer, nullable=True)
    status = Column(String(100), nullable=True)
    tour = relationship("Tour", back_populates="departures")


class TourCostItem(Base):
    __tablename__ = "tour_cost_items"
    id = Column(Integer, primary_key=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    cost_type = Column(String(100), nullable=True)
    classification = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    unit_count = Column(Integer, nullable=True)
    unit_type = Column(String(100), nullable=True)
    is_fixed = Column(Boolean, default=False)
    tour = relationship("Tour", back_populates="cost_items")


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    booking_number = Column(String(100), nullable=False)
    booking_date = Column(DateTime, default=datetime.utcnow)
    service_start_date = Column(DateTime, nullable=True)
    service_end_date = Column(DateTime, nullable=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=True)
    booking_type = Column(String(100), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    passenger_count = Column(Integer, default=0)
    adult_count = Column(Integer, default=0)
    child_count = Column(Integer, default=0)
    infant_count = Column(Integer, default=0)
    sales_channel_id = Column(Integer, ForeignKey("sales_channels.id"), nullable=True)
    sales_person_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    guide_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    unit_price = Column(Numeric(18,2), default=Decimal('0.00'))
    total_price = Column(Numeric(18,2), default=Decimal('0.00'))
    discount_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    commission_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    tax_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    grand_total = Column(Numeric(18,2), default=Decimal('0.00'))
    deposit_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    collected_total = Column(Numeric(18,2), default=Decimal('0.00'))
    remaining_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    payment_method = Column(String(100), nullable=True)
    final_payment_date = Column(DateTime, nullable=True)
    booking_status = Column(String(100), nullable=True)
    operation_status = Column(String(100), nullable=True)
    voucher_number = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    is_demo = Column(Boolean, default=False, nullable=False)
    passengers = relationship("Passenger", back_populates="booking")
    customer = relationship("Customer", back_populates="bookings")
    bookings_services = relationship("BookingService", back_populates="booking")
    collections = relationship("Collection", back_populates="booking")
    vouchers = relationship("Voucher", back_populates="booking")
    tour = relationship("Tour", back_populates="bookings")


class BookingService(Base):
    __tablename__ = "booking_services"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    service_type = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Numeric(18,2), default=Decimal('0.00'))
    total_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    booking = relationship("Booking", back_populates="bookings_services")


class Hotel(Base):
    __tablename__ = "hotels"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    address = Column(Text, nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    currency = Column(String(10), default="TRY")
    rating = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    hotel_bookings = relationship("HotelBooking", back_populates="hotel")


class HotelBooking(Base):
    __tablename__ = "hotel_bookings"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=False)
    checkin_date = Column(DateTime, nullable=True)
    checkout_date = Column(DateTime, nullable=True)
    nights = Column(Integer, default=0)
    room_count = Column(Integer, default=0)
    room_type = Column(String(100), nullable=True)
    board_type = Column(String(100), nullable=True)
    adult_count = Column(Integer, default=0)
    child_count = Column(Integer, default=0)
    infant_count = Column(Integer, default=0)
    price_per_room = Column(Numeric(18,2), default=Decimal('0.00'))
    price_per_person = Column(Numeric(18,2), default=Decimal('0.00'))
    extra_bed = Column(Numeric(18,2), default=Decimal('0.00'))
    discount_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    tax_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    total_cost = Column(Numeric(18,2), default=Decimal('0.00'))
    cancellation_policy = Column(Text, nullable=True)
    free_cancellation_until = Column(DateTime, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    booking = relationship("Booking")
    hotel = relationship("Hotel", back_populates="hotel_bookings")


class Transfer(Base):
    __tablename__ = "transfers"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=True)
    transfer_type = Column(String(100), nullable=True)
    pickup_location = Column(String(255), nullable=True)
    dropoff_location = Column(String(255), nullable=True)
    flight_number = Column(String(100), nullable=True)
    flight_time = Column(DateTime, nullable=True)
    pickup_time = Column(DateTime, nullable=True)
    passenger_count = Column(Integer, default=0)
    vehicle_type = Column(String(100), nullable=True)
    vehicle_plate = Column(String(100), nullable=True)
    driver = Column(String(255), nullable=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    purchase_cost = Column(Numeric(18,2), default=Decimal('0.00'))
    sale_price = Column(Numeric(18,2), default=Decimal('0.00'))
    payment_status = Column(String(100), nullable=True)
    operation_status = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)


class Guide(Base):
    __tablename__ = "guides"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    languages = Column(String(255), nullable=True)
    license_number = Column(String(200), nullable=True)
    specialties = Column(Text, nullable=True)
    daily_fee = Column(Numeric(18,2), default=Decimal('0.00'))
    half_day_fee = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    iban = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)


class GuideAssignment(Base):
    __tablename__ = "guide_assignments"
    id = Column(Integer, primary_key=True)
    guide_id = Column(Integer, ForeignKey("guides.id"), nullable=False)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    assigned_date = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)
    guide = relationship("Guide")


class Collection(Base):
    __tablename__ = "collections"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    collection_date = Column(DateTime, default=datetime.utcnow)
    amount = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    amount_in_tl = Column(Numeric(18,2), default=Decimal('0.00'))
    payment_method = Column(String(100), nullable=True)
    account_name = Column(String(255), nullable=True)
    transaction_reference = Column(String(255), nullable=True)
    receipt_number = Column(String(255), nullable=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    notes = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    booking = relationship("Booking", back_populates="collections")


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    supplier_type = Column(String(100), nullable=True)
    contact_person = Column(String(255), nullable=True)
    tax_office = Column(String(100), nullable=True)
    tax_number = Column(String(100), nullable=True)
    phone = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(Text, nullable=True)
    iban = Column(String(200), nullable=True)
    currency = Column(String(10), default="TRY")
    payment_terms = Column(String(255), nullable=True)
    average_payment_days = Column(Integer, nullable=True)
    risk_limit = Column(String(100), nullable=True)
    contract_start = Column(DateTime, nullable=True)
    contract_end = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)


class SupplierPayment(Base):
    __tablename__ = "supplier_payments"
    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    tour_id = Column(Integer, ForeignKey("tours.id"), nullable=True)
    invoice_reference = Column(String(255), nullable=True)
    service_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    payment_date = Column(DateTime, nullable=True)
    total_debt = Column(Numeric(18,2), default=Decimal('0.00'))
    paid_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    remaining_amount = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    payment_method = Column(String(100), nullable=True)
    account_name = Column(String(255), nullable=True)
    payment_status = Column(String(100), nullable=True)
    document_reference = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)


class CashAccount(Base):
    __tablename__ = "cash_accounts"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    currency = Column(String(10), default="TRY")
    balance = Column(Numeric(18,2), default=Decimal('0.00'))
    notes = Column(Text, nullable=True)


class BankAccount(Base):
    __tablename__ = "bank_accounts"
    id = Column(Integer, primary_key=True)
    bank_name = Column(String(255), nullable=False)
    branch = Column(String(255), nullable=True)
    iban = Column(String(255), nullable=True)
    account_number = Column(String(100), nullable=True)
    currency = Column(String(10), default="TRY")
    balance = Column(Numeric(18,2), default=Decimal('0.00'))
    notes = Column(Text, nullable=True)


class CurrencyRate(Base):
    __tablename__ = "currency_rates"
    id = Column(Integer, primary_key=True)
    currency = Column(String(10), nullable=False)
    rate = Column(Numeric(18,6), default=Decimal('1.0'))
    date = Column(DateTime, default=datetime.utcnow)


class Cancellation(Base):
    __tablename__ = "cancellations"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    cancellation_date = Column(DateTime, default=datetime.utcnow)
    reason = Column(Text, nullable=True)
    customer_refund = Column(Numeric(18,2), default=Decimal('0.00'))
    cancellation_fee = Column(Numeric(18,2), default=Decimal('0.00'))
    supplier_refund = Column(Numeric(18,2), default=Decimal('0.00'))
    supplier_penalty = Column(Numeric(18,2), default=Decimal('0.00'))
    net_cancel_result = Column(Numeric(18,2), default=Decimal('0.00'))
    refund_method = Column(String(100), nullable=True)
    document_reference = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)


class Refund(Base):
    __tablename__ = "refunds"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    refund_date = Column(DateTime, default=datetime.utcnow)
    amount = Column(Numeric(18,2), default=Decimal('0.00'))
    currency = Column(String(10), default="TRY")
    exchange_rate = Column(Numeric(18,6), default=Decimal('1.0'))
    refund_method = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)


class Voucher(Base):
    __tablename__ = "vouchers"
    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    voucher_number = Column(String(200), nullable=True)
    issue_date = Column(DateTime, default=datetime.utcnow)
    customer_name = Column(String(255), nullable=True)
    service_name = Column(String(255), nullable=True)
    travel_date = Column(DateTime, nullable=True)
    pickup_location = Column(String(255), nullable=True)
    dropoff_location = Column(String(255), nullable=True)
    hotel_info = Column(Text, nullable=True)
    transfer_info = Column(Text, nullable=True)
    guide_info = Column(Text, nullable=True)
    included_services = Column(Text, nullable=True)
    excluded_services = Column(Text, nullable=True)
    emergency_contact = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    booking = relationship("Booking", back_populates="vouchers")
