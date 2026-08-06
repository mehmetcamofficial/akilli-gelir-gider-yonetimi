from .models import Base, Category, Transaction
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime, timedelta
from decimal import Decimal
import random


def seed_demo_data():
    # import engine lazily to avoid circular imports
    from .db import engine
    Session = sessionmaker(bind=engine)
    session = Session()

    # if categories exist, skip
    if session.query(Category).count() > 0:
        session.close()
        return

    # create simple categories
    income = Category(name="Ürün satışı")
    service = Category(name="Hizmet geliri")
    expense = Category(name="Mal alışları")
    session.add_all([income, service, expense])
    session.commit()

    # create transactions
    for i in range(1, 51):
        ttype = "income" if i % 2 == 0 else "expense"
        amount = Decimal(random.randint(1000, 50000)) / Decimal(100)
        tax = (amount * Decimal("0.18")) if ttype == "income" else (amount * Decimal("0.08"))
        grand = amount + tax
        txn = Transaction(
            transaction_type=ttype,
            transaction_date=datetime.utcnow() - timedelta(days=random.randint(0, 365)),
            invoice_number=f"FAT-{i:04d}",
            description=f"Demo işlem {i}",
            category_id=income.id if ttype == "income" else expense.id,
            party_name=f"Firma {random.randint(1,20)}",
            subtotal=amount,
            tax_total=tax,
            grand_total=grand,
            paid_amount=Decimal("0.00"),
            remaining_amount=grand,
            payment_status="Ödenmedi",
        )
        session.add(txn)

    session.commit()
    session.close()


def init_and_seed():
    from .db import engine
    Base.metadata.create_all(bind=engine)
    seed_demo_data()


def migrate_add_invoice_type():
    # Add invoice_type column to transactions if missing (SQLite)
    from .db import engine
    conn = engine.connect()
    res = conn.exec_driver_sql("PRAGMA table_info(transactions);")
    cols = [r[1] for r in res.fetchall()]
    if 'invoice_type' not in cols:
        try:
            conn.exec_driver_sql("ALTER TABLE transactions ADD COLUMN invoice_type VARCHAR(20);")
        except Exception:
            pass
    conn.close()


if __name__ == "__main__":
    init_and_seed()
