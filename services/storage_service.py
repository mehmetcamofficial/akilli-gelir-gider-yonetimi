import hashlib
import os
from datetime import datetime

from sqlalchemy.orm import Session

from database.db import IS_POSTGRESQL
from database.models import AuditLog, Document
from services.google_drive_config import (
    delete_drive_file,
    download_drive_file,
    has_valid_drive_config,
    upload_drive_file,
)


class DuplicateDocumentError(ValueError):
    def __init__(self, document):
        self.document = document
        super().__init__(f"Bu belgenin aynısı arşivde mevcut (Belge #{document.id}).")


def safe_filename(name):
    cleaned = "".join(character for character in str(name or "belge") if character.isalnum() or character in (" ", "-", "_", ".")).rstrip()
    return cleaned or "belge"


def document_hash(content):
    return hashlib.sha256(content).hexdigest()


def find_duplicate(db, content):
    return db.query(Document).filter(Document.file_hash == document_hash(content)).first()


def store_document_bytes(content, filename, mime_type, db: Session, transaction_id=None, is_demo=False, commit=True):
    digest = document_hash(content)
    existing = db.query(Document).filter(Document.file_hash == digest).first()
    if existing:
        db.add(AuditLog(event_type="duplicate_document_detected", entity_type="document", entity_id=existing.id, action="duplicate_detection", new_values={"file_hash": digest, "filename": safe_filename(filename)}, source="document_archive", status="Mükerrer"))
        if commit: db.commit()
        return existing, True

    now = datetime.utcnow()
    original_name = safe_filename(filename)
    stored_name = f"{now.strftime('%Y%m%d%H%M%S')}_{digest[:10]}_{original_name}"
    provider, path, drive_id, web_link = "local", None, None, None

    if has_valid_drive_config():
        uploaded = upload_drive_file(stored_name, mime_type, content)
        provider = "google_drive"
        drive_id = uploaded["id"]
        web_link = uploaded.get("webViewLink")
    elif IS_POSTGRESQL:
        raise RuntimeError("Production belge depolaması için Google Drive bağlantısı zorunludur.")
    else:
        directory = os.path.join(os.getcwd(), "uploads", now.strftime("%Y"), now.strftime("%m"))
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, stored_name)
        with open(path, "wb") as handle:
            handle.write(content)

    document = Document(
        original_filename=filename,
        stored_filename=stored_name,
        file_path=path,
        file_type=mime_type,
        file_hash=digest,
        file_size=len(content),
        storage_provider=provider,
        drive_file_id=drive_id,
        drive_web_view_link=web_link,
        uploaded_at=now,
        transaction_id=transaction_id,
        is_demo=is_demo,
    )
    db.add(document)
    db.flush()
    db.add(AuditLog(event_type="document_uploaded", entity_type="document", entity_id=document.id, action="upload", new_values={"filename": original_name, "file_hash": digest, "storage_provider": provider, "drive_file_id": drive_id}, source="document_archive", status="Tamamlandı"))
    if commit:
        try:
            db.commit()
            db.refresh(document)
        except Exception:
            db.rollback()
            if drive_id:
                try:
                    delete_drive_file(drive_id)
                except Exception:
                    pass
            raise
    else:
        db.flush()
    return document, False


def save_uploaded_file(uploaded_file, invoice_type, db: Session, transaction_id=None):
    del invoice_type  # Kept for backwards-compatible callers.
    content = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    document, _ = store_document_bytes(
        content,
        uploaded_file.name,
        getattr(uploaded_file, "type", None),
        db,
        transaction_id=transaction_id,
    )
    return document


def load_document_bytes(document):
    if document.drive_file_id:
        return download_drive_file(document.drive_file_id, document.file_type).getvalue()
    if document.file_path and os.path.isfile(document.file_path):
        with open(document.file_path, "rb") as handle:
            return handle.read()
    raise FileNotFoundError("Belge içeriği kalıcı depolamada bulunamadı.")


def delete_document_content(document):
    if document.drive_file_id:
        delete_drive_file(document.drive_file_id)
    elif document.file_path and os.path.isfile(document.file_path):
        os.remove(document.file_path)
