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
    transaction = relationship("Transaction", back_populates="documents")


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

