from sqlalchemy.orm import Session
from decimal import Decimal
from database.models import Product, StockMovement


def update_purchase_price_and_stock(session: Session, product_id: int, qty: Decimal, purchase_price: Decimal, invoice_id: int = None):
    # qty: incoming quantity (positive). purchase_price per unit.
    product = session.query(Product).filter(Product.id == product_id).first()
    if not product:
        return

    # compute new average cost
    current_stock = Decimal(product.stock or 0)
    current_avg = Decimal(product.avg_purchase_price or 0)
    new_qty = Decimal(qty)
    new_price = Decimal(purchase_price)

    if current_stock + new_qty > 0:
        new_avg = (current_stock * current_avg + new_qty * new_price) / (current_stock + new_qty)
    else:
        new_avg = new_price

    product.last_purchase_price = new_price
    product.avg_purchase_price = new_avg
    product.stock = current_stock + new_qty

    # record stock movement
    sm = StockMovement(product_id=product.id, qty=new_qty, movement_type='in', related_invoice_id=invoice_id)
    session.add(sm)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def record_sale_and_reduce_stock(session: Session, product_id: int, qty: Decimal, invoice_id: int = None):
    product = session.query(Product).filter(Product.id == product_id).first()
    if not product:
        return
    current_stock = Decimal(product.stock or 0)
    reduce_qty = Decimal(qty)
    product.stock = current_stock - reduce_qty
    sm = StockMovement(product_id=product.id, qty=reduce_qty, movement_type='out', related_invoice_id=invoice_id)
    session.add(sm)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def adjust_stock_delta(session: Session, product_id: int, delta_qty: Decimal, invoice_id: int = None, movement_type: str = 'adjust'):
    """Apply a positive or negative delta to product.stock and record a StockMovement."""
    product = session.query(Product).filter(Product.id == product_id).first()
    if not product:
        return
    product.stock = Decimal(product.stock or 0) + Decimal(delta_qty)
    sm = StockMovement(product_id=product.id, qty=Decimal(delta_qty), movement_type=movement_type, related_invoice_id=invoice_id)
    session.add(sm)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product
