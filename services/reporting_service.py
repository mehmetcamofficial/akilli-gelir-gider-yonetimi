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


def _turkish_date(dt):
    if dt is None:
        return ''
    if hasattr(dt, 'strftime'):
        return dt.strftime('%d.%m.%Y')
    return str(dt)


def _draw_header(c, title, logo_path=None):
    width, height = A4
    y = height - 15 * mm
    # logo
    if logo_path and os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, 15 * mm, y - 12 * mm, width=30 * mm, height=12 * mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    # title centered
    c.setFont('Helvetica-Bold', 12)
    c.drawCentredString(width / 2.0, y, title)
    # date right
    c.setFont('Helvetica', 9)
    c.drawRightString(width - 15 * mm, y, _turkish_date(datetime.utcnow()))


def _draw_footer(c):
    width, height = A4
    page_num = c.getPageNumber()
    footer_text = f"Sayfa {page_num}"
    c.setFont('Helvetica', 8)
    c.drawRightString(width - 15 * mm, 10 * mm, footer_text)


def _draw_table(c, x_start, y_start, col_widths, headers, rows, row_height=6 * mm, rows_per_page=40, logo_path=None, title=None):
    """Draws a simple table with borders. Returns when finished."""
    width, height = A4
    x = x_start
    y = y_start
    # draw header
    c.setFont('Helvetica-Bold', 9)
    padding = 2 * mm
    # vertical lines positions
    vpos = [x]
    for w in col_widths:
        vpos.append(vpos[-1] + w)

    def draw_table_grid(current_y, num_rows_on_page):
        # horizontal lines
        top = current_y
        bottom = current_y - (num_rows_on_page + 1) * row_height
        # draw outer rect
        c.line(x_start, top, vpos[-1], top)
        c.line(x_start, bottom, vpos[-1], bottom)
        # verticals
        for xp in vpos:
            c.line(xp, top, xp, bottom)

    # Draw header row text
    for i, h in enumerate(headers):
        tx = vpos[i] + padding
        c.drawString(tx, y, str(h))
    y -= row_height
    c.setFont('Helvetica', 9)

    row_count = 0
    page_row_count = 0
    for r in rows:
        if page_row_count >= rows_per_page:
            # finish page
            draw_table_grid(y + (rows_per_page + 1) * row_height, rows_per_page)
            _draw_footer(c)
            c.showPage()
            if title or logo_path:
                _draw_header(c, title or '', logo_path=logo_path)
            y = y_start - row_height
            c.setFont('Helvetica', 9)
            page_row_count = 0
        # draw row cells
        for i, cell in enumerate(r):
            tx = vpos[i] + padding
            # right align numbers
            try:
                # numeric?
                float(cell)
                c.drawRightString(vpos[i+1] - padding, y, str(cell))
            except Exception:
                c.drawString(tx, y, str(cell))
        y -= row_height
        row_count += 1
        page_row_count += 1

    # final grid for last page
    draw_table_grid(y + (page_row_count + 1) * row_height, page_row_count)



def generate_product_profitability_pdf(session, start_date, end_date, logo_path=None):
    """Return PDF bytes for product profitability between dates."""
    font_name = _register_dejavu()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y_start = height - 30 * mm
    title = f"Ürün Kârlılığı: {start_date} - {end_date}"

    _draw_header(c, title, logo_path=logo_path)
    y = y_start - 10 * mm

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

        # Draw header row
        c.setFont('Helvetica-Bold', 10)
        c.drawString(20 * mm, y, 'Ürün')
        c.drawString(95 * mm, y, 'Adet')
        c.drawString(120 * mm, y, 'Gelir')
        c.drawString(150 * mm, y, 'Maliyet')
        c.drawString(180 * mm, y, 'Kâr')
        y -= 7 * mm
        c.setFont('Helvetica', 10)

        # prepare rows for table helper
        table_rows = []
        for name, vals in rows.items():
            profit = vals['revenue'] - vals['cost']
            table_rows.append([name, _format_currency(vals['qty']), _format_currency(vals['revenue']), _format_currency(vals['cost']), _format_currency(profit)])

        col_widths = [75 * mm, 25 * mm, 30 * mm, 30 * mm, 30 * mm]
        headers = ['Ürün', 'Adet', 'Gelir', 'Maliyet', 'Kâr']
        _draw_table(c, 20 * mm, y + 7 * mm, col_widths, headers, table_rows, row_height=7 * mm, rows_per_page=30, logo_path=logo_path, title=title)
    except Exception:
        c.drawString(20 * mm, y, 'Veri alınamadı veya modeller yüklenemedi.')

    _draw_footer(c)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def generate_invoice_list_pdf(session, start_date, end_date, logo_path=None):
    """Return PDF bytes for transactions between dates."""
    font_name = _register_dejavu()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y_start = height - 30 * mm
    title = f"Fatura / İşlem Listesi: {start_date} - {end_date}"

    _draw_header(c, title, logo_path=logo_path)
    y = y_start - 10 * mm

    try:
        from database.models import Transaction
        txs = session.query(Transaction).filter(Transaction.transaction_date >= start_date).filter(Transaction.transaction_date <= end_date).order_by(Transaction.transaction_date).all()
        c.setFont('Helvetica-Bold', 10)
        c.drawString(20 * mm, y, 'Tarih')
        c.drawString(55 * mm, y, 'No')
        c.drawString(85 * mm, y, 'Taraf')
        c.drawString(140 * mm, y, 'Tür')
        c.drawRightString(205 * mm, y, 'Tutar')
        y -= 7 * mm
        # build rows for table helper
        table_rows = []
        for t in txs:
            date_str = t.transaction_date.strftime('%d.%m.%Y') if hasattr(t.transaction_date, 'strftime') else str(t.transaction_date)
            table_rows.append([date_str, str(t.invoice_number or ''), str(t.party_name or ''), str(t.transaction_type or ''), _format_currency(t.grand_total or 0)])

        col_widths = [30 * mm, 30 * mm, 60 * mm, 30 * mm, 30 * mm]
        headers = ['Tarih', 'No', 'Taraf', 'Tür', 'Tutar']
        _draw_table(c, 20 * mm, y + 7 * mm, col_widths, headers, table_rows, row_height=7 * mm, rows_per_page=30, logo_path=logo_path, title=title)
    except Exception:
        c.drawString(20 * mm, y, 'İşlem verisi alınırken hata oluştu.')

    _draw_footer(c)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()
