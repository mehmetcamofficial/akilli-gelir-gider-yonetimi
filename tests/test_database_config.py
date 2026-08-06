from datetime import datetime

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from database import db
from database.models import Base, Booking, Customer, Transaction


def test_postgresql_url_uses_psycopg_without_exposing_credentials(monkeypatch):
    secret = "postgresql://example:secret@db.invalid:5432/postgres"
    monkeypatch.setattr(db.st, "secrets", {"DATABASE_URL": secret})
    normalized = db._database_url()
    assert normalized.startswith("postgresql+psycopg://")
    assert normalized.endswith("/postgres")


def test_local_fallback_is_sqlite(monkeypatch):
    monkeypatch.setattr(db.st, "secrets", {})
    assert db._database_url() == "sqlite:///database/app.db"


def test_customer_booking_and_transaction_survive_new_engine(tmp_path):
    database_file = tmp_path / "persistence.db"
    url = f"sqlite:///{database_file}"
    first_engine = create_engine(url)
    Base.metadata.create_all(first_engine)
    FirstSession = sessionmaker(bind=first_engine)
    first = FirstSession()
    customer = Customer(first_name="Kalıcı", last_name="Test", email="persistent@example.com")
    first.add(customer)
    first.flush()
    booking = Booking(booking_number="PERSIST-BOOKING", booking_date=datetime(2026, 8, 7), customer_id=customer.id, grand_total=1250)
    transaction = Transaction(transaction_type="income", invoice_number="PERSIST-INVOICE", grand_total=1250)
    first.add_all([booking, transaction])
    first.commit()
    first.close()
    first_engine.dispose()

    rebooted_engine = create_engine(url)
    RebootedSession = sessionmaker(bind=rebooted_engine)
    rebooted = RebootedSession()
    assert rebooted.query(Customer).filter_by(email="persistent@example.com").one()
    assert rebooted.query(Booking).filter_by(booking_number="PERSIST-BOOKING").one()
    assert rebooted.query(Transaction).filter_by(invoice_number="PERSIST-INVOICE").one()
    assert len(inspect(rebooted_engine).get_table_names()) == len(Base.metadata.tables)
    rebooted.close()
    rebooted_engine.dispose()


def test_health_check_never_returns_database_url():
    result = db.database_health()
    assert "url" not in result
    assert "password" not in result
    assert result["provider"] in {"PostgreSQL / Supabase", "SQLite (yerel geliştirme)"}
