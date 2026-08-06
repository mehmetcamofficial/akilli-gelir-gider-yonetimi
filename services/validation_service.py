from sqlalchemy.orm import Session
from decimal import Decimal
from database.models import Transaction
from typing import List


def is_duplicate_invoice(session: Session, invoice_number: str, party_name: str) -> bool:
    if not invoice_number:
        return False
    q = session.query(Transaction).filter(Transaction.invoice_number == invoice_number)
    if party_name:
        q = q.filter(Transaction.party_name == party_name)
    return session.query(q.exists()).scalar()


def validate_line_totals(line_items: List[dict]) -> dict:
    # returns sums: subtotal, tax_total, grand_total
    subtotal = Decimal('0.00')
    tax_total = Decimal('0.00')
    grand = Decimal('0.00')
    for r in line_items:
        qty = Decimal(str(r.get('quantity', 0)))
        unit_price = Decimal(str(r.get('unit_price', 0)))
        discount = Decimal(str(r.get('discount_amount', 0)))
        add_cost = Decimal(str(r.get('additional_cost', 0)))
        tax = Decimal(str(r.get('tax_amount', 0)))
        line_sub = qty * unit_price - discount + add_cost
        subtotal += (qty * unit_price - discount)
        tax_total += tax
        grand += line_sub + tax
    return {"subtotal": subtotal, "tax_total": tax_total, "grand_total": grand}
