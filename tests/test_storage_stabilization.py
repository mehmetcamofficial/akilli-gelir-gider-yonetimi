from io import BytesIO

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from database import db as database_db
from database.migrations import delete_demo_data, seed_demo_data
from database.models import Base, Booking, Customer, Document, Supplier, Tour, Transaction
from services import storage_service


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'storage.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_drive_upload_metadata_duplicate_and_download(tmp_path, monkeypatch):
    engine, session = _session(tmp_path)
    uploads = []
    monkeypatch.setattr(storage_service, "has_valid_drive_config", lambda: True)
    monkeypatch.setattr(storage_service, "upload_drive_file", lambda name, mime, content: uploads.append(content) or {"id": "drive-123", "webViewLink": "https://drive.example/file"})
    monkeypatch.setattr(storage_service, "download_drive_file", lambda file_id, mime: BytesIO(b"same-document"))

    first, duplicate = storage_service.store_document_bytes(b"same-document", "invoice.pdf", "application/pdf", session)
    second, second_duplicate = storage_service.store_document_bytes(b"same-document", "copy.pdf", "application/pdf", session)

    assert not duplicate
    assert second_duplicate
    assert first.id == second.id
    assert len(uploads) == 1
    assert first.storage_provider == "google_drive"
    assert first.drive_file_id == "drive-123"
    assert storage_service.load_document_bytes(first) == b"same-document"
    session.close()
    engine.dispose()


def test_document_metadata_survives_engine_reboot(tmp_path):
    path = tmp_path / "persistent.db"
    url = f"sqlite:///{path}"
    engine = create_engine(url); Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Document(original_filename="voucher.pdf", file_hash="a" * 64, file_size=10, storage_provider="google_drive", drive_file_id="persistent-drive-id", drive_web_view_link="https://drive.example/persistent"))
    session.commit(); session.close(); engine.dispose()

    rebooted = create_engine(url); session = sessionmaker(bind=rebooted)()
    document = session.query(Document).filter_by(drive_file_id="persistent-drive-id").one()
    assert document.original_filename == "voucher.pdf"
    assert document.storage_provider == "google_drive"
    session.close(); rebooted.dispose()


def test_schema_has_phase3_application_tables_and_drive_columns(tmp_path):
    engine, session = _session(tmp_path)
    assert len(Base.metadata.tables) == 90
    columns = {column["name"] for column in inspect(engine).get_columns("documents")}
    assert {"storage_provider", "drive_file_id", "drive_web_view_link"} <= columns
    session.close(); engine.dispose()


def test_demo_deletion_removes_dashboard_demo_values(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database_db, "engine", engine)
    seed_demo_data(force=True)
    result = delete_demo_data()
    session = sessionmaker(bind=engine)()
    assert result["bookings"] == 2
    assert session.query(Booking).filter(Booking.is_demo.is_(True)).count() == 0
    assert session.query(Tour).filter(Tour.is_demo.is_(True)).count() == 0
    assert session.query(Customer).filter(Customer.is_demo.is_(True)).count() == 0
    assert session.query(Supplier).filter(Supplier.is_demo.is_(True)).count() == 0
    assert session.query(Transaction).filter(Transaction.is_demo.is_(True)).count() == 0
    session.close(); engine.dispose()
