import os
import hashlib
from datetime import datetime
from database.models import Document
from sqlalchemy.orm import Session


def safe_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in (" ","-","_",".")).rstrip()


def save_uploaded_file(uploaded_file, invoice_type: str, db: Session, transaction_id: int = None) -> Document:
    # invoice_type: 'income' or 'expense'
    content = uploaded_file.read()
    sha = hashlib.sha256(content).hexdigest()

    existing = db.query(Document).filter_by(file_hash=sha).first()
    if existing:
        return existing

    now = datetime.utcnow()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    base_dir = os.path.join(os.getcwd(), "uploads")
    if invoice_type == "income":
        sub = os.path.join(base_dir, "income_invoices", year, month)
    else:
        sub = os.path.join(base_dir, "expense_invoices", year, month)

    os.makedirs(sub, exist_ok=True)

    orig_name = safe_filename(uploaded_file.name)
    stored_name = f"{now.strftime('%Y%m%d%H%M%S')}_{orig_name}"
    path = os.path.join(sub, stored_name)
    with open(path, "wb") as f:
        f.write(content)

    doc = Document(
        original_filename=uploaded_file.name,
        stored_filename=stored_name,
        file_path=path,
        file_type=uploaded_file.type if hasattr(uploaded_file, 'type') else None,
        file_hash=sha,
        file_size=len(content),
        uploaded_at=now,
        transaction_id=transaction_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc
