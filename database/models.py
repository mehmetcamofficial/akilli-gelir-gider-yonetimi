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
