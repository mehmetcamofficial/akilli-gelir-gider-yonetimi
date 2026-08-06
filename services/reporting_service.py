from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os


def _register_dejavu():
    possible = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/Library/Fonts/DejaVuSans.ttf',
        '/usr/local/share/fonts/DejaVuSans.ttf',
        os.path.join(os.path.dirname(__file__), 'fonts', 'DejaVuSans.ttf')
    ]
    for p in possible:
        if os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont('DejaVuSans', p))
                return 'DejaVuSans'
            except Exception:
                continue
    # fallback to built-in
    return None


def _format_currency(v):
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def generate_product_profitability_pdf(session, start_date, end_date):
    """Return PDF bytes for product profitability between dates."""
    font_name = _register_dejavu()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 20 * mm
    title = f"Ürün Kârlılığı: {start_date} - {end_date}"
    if font_name:
        c.setFont(font_name, 14)
    else:
        c.setFont('Helvetica-Bold', 14)
    c.drawString(20 * mm, y, title)
    y -= 10 * mm

    # Query profitability
    q = session.query(
        session.bind.metadata.tables.get('product') or None
    )
    # We'll build a simple table by querying InvoiceItem/Product via SQLAlchemy core-like access
    # Fallback: attempt ORM-style queries if models are available in session
    try:
        from database.models import InvoiceItem, Product, Transaction
        items = session.query(Product.name, InvoiceItem.quantity, InvoiceItem.unit_price, InvoiceItem.total_price, Product.avg_purchase_price).join(InvoiceItem, InvoiceItem.product_id==Product.id).join(Transaction, InvoiceItem.transaction_id==Transaction.id).filter(Transaction.transaction_date >= start_date).filter(Transaction.transaction_date <= end_date).all()
        rows = {}
        for name, qty, unit_price, total_price, avg_purchase in items:
            qty = float(qty or 0)
            revenue = float(total_price or 0)
            cost = qty * float(avg_purchase or 0)
            if name not in rows:
                rows[name] = {'revenue': 0.0, 'cost': 0.0, 'qty': 0.0}
            rows[name]['revenue'] += revenue
            rows[name]['cost'] += cost
            rows[name]['qty'] += qty

        # Draw header
        if font_name:
            c.setFont(font_name, 10)
        else:
            c.setFont('Helvetica', 10)
        c.drawString(20 * mm, y, 'Ürün')
        c.drawString(90 * mm, y, 'Adet')
        c.drawString(110 * mm, y, 'Gelir')
        c.drawString(140 * mm, y, 'Maliyet')
        c.drawString(165 * mm, y, 'Kâr')
        y -= 7 * mm

        for name, vals in rows.items():
            if y < 30 * mm:
                c.showPage()
                y = height - 20 * mm
                if font_name:
                    c.setFont(font_name, 10)
                else:
                    c.setFont('Helvetica', 10)
            profit = vals['revenue'] - vals['cost']
            c.drawString(20 * mm, y, str(name))
            c.drawRightString(120 * mm, y, _format_currency(vals['qty']))
            c.drawRightString(150 * mm, y, _format_currency(vals['revenue']))
            c.drawRightString(180 * mm, y, _format_currency(vals['cost']))
            c.drawRightString(205 * mm, y, _format_currency(profit))
            y -= 6 * mm
    except Exception:
        c.drawString(20 * mm, y, 'Veri alınamadı veya modeller yüklenemedi.')

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def generate_invoice_list_pdf(session, start_date, end_date):
    """Return PDF bytes for transactions between dates."""
    font_name = _register_dejavu()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 20 * mm
    title = f"Fatura / İşlem Listesi: {start_date} - {end_date}"
    if font_name:
        c.setFont(font_name, 14)
    else:
        c.setFont('Helvetica-Bold', 14)
    c.drawString(20 * mm, y, title)
    y -= 10 * mm

    try:
        from database.models import Transaction
        txs = session.query(Transaction).filter(Transaction.transaction_date >= start_date).filter(Transaction.transaction_date <= end_date).order_by(Transaction.transaction_date).all()
        if font_name:
            c.setFont(font_name, 10)
        else:
            c.setFont('Helvetica', 10)
        c.drawString(20 * mm, y, 'Tarih')
        c.drawString(55 * mm, y, 'No')
        c.drawString(85 * mm, y, 'Taraf')
        c.drawString(140 * mm, y, 'Tür')
        c.drawRightString(205 * mm, y, 'Tutar')
        y -= 7 * mm
        for t in txs:
            if y < 30 * mm:
                c.showPage()
                y = height - 20 * mm
            date_str = t.transaction_date.strftime('%Y-%m-%d') if hasattr(t.transaction_date, 'strftime') else str(t.transaction_date)
            c.drawString(20 * mm, y, date_str)
            c.drawString(55 * mm, y, str(t.invoice_number or ''))
            c.drawString(85 * mm, y, str(t.party_name or ''))
            c.drawString(140 * mm, y, str(t.transaction_type or ''))
            c.drawRightString(205 * mm, y, _format_currency(t.grand_total or 0))
            y -= 6 * mm
    except Exception:
        c.drawString(20 * mm, y, 'İşlem verisi alınırken hata oluştu.')

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()
