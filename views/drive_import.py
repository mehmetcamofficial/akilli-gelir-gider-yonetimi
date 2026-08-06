from io import BytesIO
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Transaction, Booking
from services.google_drive_config import (
    download_drive_file,
    get_drive_service,
    has_valid_drive_config,
    initialize_drive_state,
    list_drive_files,
)
from services.drive_import_service import normalize_column_name, parse_decimal, parse_date
from utils.ui import page_header, section_header, empty_state

SUPPORTED_EXTENSIONS = [".xlsx", ".xls", ".csv"]
FIELD_ORDER = [
    ("transaction_date", "Tarih"),
    ("due_date", "Vade Tarihi"),
    ("transaction_type", "İşlem Türü"),
    ("description", "Açıklama"),
    ("party_name", "Müşteri / Tedarikçi"),
    ("tour", "Tur"),
    ("booking_number", "Rezervasyon No"),
    ("invoice_number", "Fatura No"),
    ("grand_total", "Tutar"),
    ("income", "Gelir"),
    ("expense", "Gider"),
    ("tax_total", "KDV"),
    ("currency", "Para Birimi"),
    ("payment_status", "Ödeme Durumu"),
]


def _format_drive_file_type(mime_type):
    if mime_type == "application/vnd.google-apps.spreadsheet":
        return "Google Sheets"
    if mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return "XLSX"
    if mime_type == "application/vnd.ms-excel":
        return "XLS"
    if mime_type == "text/csv":
        return "CSV"
    return mime_type


def _human_readable_size(size):
    if not size:
        return "—"
    try:
        size = int(size)
    except Exception:
        return str(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size} {unit}"
        size //= 1024
    return f"{size} TB"


def _save_import_rows(rows):
    session = sessionmaker(bind=engine)()
    try:
        imported, skipped = 0, 0
        for raw in rows:
            existing = None
            if raw.get("invoice_number"):
                existing = session.query(Transaction).filter(
                    Transaction.invoice_number == raw["invoice_number"],
                    Transaction.party_name == raw.get("party_name"),
                ).first()
            if existing:
                skipped += 1
                continue
            txn = Transaction(
                transaction_type=raw.get("transaction_type", "income"),
                transaction_date=raw.get("transaction_date") or datetime.utcnow(),
                due_date=raw.get("due_date"),
                invoice_number=raw.get("invoice_number") or None,
                description=raw.get("description") or None,
                party_name=raw.get("party_name") or None,
                currency=raw.get("currency", "TRY"),
                exchange_rate=1,
                subtotal=raw.get("subtotal", parse_decimal(0)),
                tax_total=raw.get("tax_total", parse_decimal(0)),
                grand_total=raw.get("grand_total", parse_decimal(0)),
                paid_amount=parse_decimal(0),
                remaining_amount=raw.get("grand_total", parse_decimal(0)),
                payment_status=raw.get("payment_status", "Ödenmedi"),
                invoice_type="sale" if raw.get("transaction_type") == "income" else "purchase",
            )
            if raw.get("booking_number"):
                booking = session.query(Booking).filter(
                    Booking.booking_number == raw["booking_number"]
                ).first()
                if booking:
                    txn.description = (
                        f"{txn.description or ''} | Rezervasyon: {booking.booking_number}".strip(" | ")
                    )
            session.add(txn)
            imported += 1
        session.commit()
        return imported, skipped
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()



def _get_sheet_names(file_bytes, filename):
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        return ["CSV"]
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    return pd.ExcelFile(BytesIO(file_bytes), engine=engine).sheet_names


def _load_dataframe(file_bytes, filename, sheet_name=None):
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        return pd.read_csv(BytesIO(file_bytes))
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    return pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name, engine=engine)


def _guess_column_mapping(columns):
    mapping = {}
    normalized = [normalize_column_name(col) for col in columns]
    for field_key, _ in FIELD_ORDER:
        guess = "<Boş>"
        for col, norm in zip(columns, normalized):
            if field_key == "transaction_date" and norm in ["tarih", "işlem tarihi", "belge tarihi"]:
                guess = col
                break
            if field_key == "due_date" and norm in ["vade tarihi", "ödeme tarihi"]:
                guess = col
                break
            if field_key == "description" and norm in ["açıklama", "not"]:
                guess = col
                break
            if field_key == "currency" and norm in ["para birimi", "döviz", "currency"]:
                guess = col
                break
            if field_key == "income" and "gelir" in norm:
                guess = col
                break
            if field_key == "expense" and "gider" in norm:
                guess = col
                break
            if FIELD_ORDER and normalize_column_name(col) in [k for k, _ in FIELD_ORDER]:
                if field_key == normalize_column_name(col):
                    guess = col
                    break
            if field_key == "party_name" and any(token in norm for token in ["müşteri", "tedarikçi", "firma", "taraf"]):
                guess = col
                break
            if field_key == "transaction_type" and any(token in norm for token in ["işlem türü", "tür", "type"]):
                guess = col
                break
            if field_key == "invoice_number" and any(token in norm for token in ["fatura", "belge no", "invoice"]):
                guess = col
                break
            if field_key == "booking_number" and any(token in norm for token in ["rezervasyon", "booking"]):
                guess = col
                break
            if field_key == "tour" and "tur" in norm:
                guess = col
                break
            if field_key == "grand_total" and any(token in norm for token in ["tutar", "toplam", "genel toplam"]):
                guess = col
                break
            if field_key == "tax_total" and any(token in norm for token in ["kdv", "vergiler", "vergi"]):
                guess = col
                break
            if field_key == "payment_status" and any(token in norm for token in ["ödeme durumu", "tahsilat durumu", "durum"]):
                guess = col
                break
        mapping[field_key] = guess
    return mapping


def _build_import_rows(df, mapping):
    rows = []
    for _, row in df.iterrows():
        raw = {}
        if mapping["transaction_date"] != "<Boş>":
            raw["transaction_date"] = parse_date(row.get(mapping["transaction_date"]))
        if mapping["due_date"] != "<Boş>":
            raw["due_date"] = parse_date(row.get(mapping["due_date"]))
        if mapping["transaction_type"] != "<Boş>":
            raw["transaction_type"] = str(row.get(mapping["transaction_type"]) or "").strip()
        if mapping["description"] != "<Boş>":
            raw["description"] = str(row.get(mapping["description"]) or "").strip()
        if mapping["party_name"] != "<Boş>":
            raw["party_name"] = str(row.get(mapping["party_name"]) or "").strip()
        if mapping["tour"] != "<Boş>":
            raw["tour"] = str(row.get(mapping["tour"]) or "").strip()
        if mapping["booking_number"] != "<Boş>":
            raw["booking_number"] = str(row.get(mapping["booking_number"]) or "").strip()
        if mapping["invoice_number"] != "<Boş>":
            raw["invoice_number"] = str(row.get(mapping["invoice_number"]) or "").strip()
        if mapping["tax_total"] != "<Boş>":
            raw["tax_total"] = parse_decimal(row.get(mapping["tax_total"]))
        if mapping["currency"] != "<Boş>":
            raw["currency"] = str(row.get(mapping["currency"]) or "TRY").strip()
        if mapping["payment_status"] != "<Boş>":
            raw["payment_status"] = str(row.get(mapping["payment_status"]) or "").strip()

        income_val = None
        if mapping["income"] != "<Boş>":
            income_val = parse_decimal(row.get(mapping["income"]))
        expense_val = None
        if mapping["expense"] != "<Boş>":
            expense_val = parse_decimal(row.get(mapping["expense"]))
        if mapping["grand_total"] != "<Boş>":
            raw["grand_total"] = parse_decimal(row.get(mapping["grand_total"]))
        elif income_val is not None or expense_val is not None:
            if income_val is None:
                raw["grand_total"] = -abs(expense_val)
            elif expense_val is None:
                raw["grand_total"] = abs(income_val)
            else:
                raw["grand_total"] = income_val - expense_val

        if mapping["transaction_type"] == "<Boş>":
            if income_val is not None and expense_val is None:
                raw["transaction_type"] = "income"
            elif expense_val is not None and income_val is None:
                raw["transaction_type"] = "expense"
            elif raw.get("grand_total") is not None:
                raw["transaction_type"] = "income" if raw["grand_total"] >= 0 else "expense"

        raw["currency"] = raw.get("currency", "TRY") or "TRY"
        raw["payment_status"] = raw.get("payment_status", "Ödenmedi") or "Ödenmedi"
        raw["description"] = raw.get("description", "")
        raw["party_name"] = raw.get("party_name", "")
        raw["invoice_number"] = raw.get("invoice_number", "")
        raw["booking_number"] = raw.get("booking_number", "")
        raw["transaction_type"] = raw.get("transaction_type", "income")
        raw["grand_total"] = raw.get("grand_total", parse_decimal(None))
        raw["tax_total"] = raw.get("tax_total", parse_decimal(None))
        raw["subtotal"] = raw.get("subtotal", parse_decimal(raw["grand_total"] - raw["tax_total"]))

        if raw["grand_total"] == parse_decimal(None):
            continue
        rows.append(raw)
    return rows


def _render_mapping_section(df, ui_prefix):
    columns = list(df.columns)
    if not columns:
        return {}
    mapping = _guess_column_mapping(columns)
    st.markdown("**Kolon Eşlemesi**")
    left, right = st.columns(2, gap="large")
    for index, (field_key, field_label) in enumerate(FIELD_ORDER):
        target = mapping[field_key] if mapping[field_key] in columns else "<Boş>"
        container = left if index % 2 == 0 else right
        with container:
            mapping[field_key] = st.selectbox(
                field_label,
                ["<Boş>"] + columns,
                index=(columns.index(target) + 1 if target in columns else 0),
                key=f"{ui_prefix}_map_{field_key}",
            )
    return mapping


def _preview_rows(rows):
    if not rows:
        st.warning("Aktarılabilecek veri bulunamadı. Lütfen kolon eşlemesini kontrol edin.")
        return
    st.write(f"**Aktarılabilecek kayıt sayısı:** {len(rows)}")
    st.dataframe(pd.DataFrame(rows[:5]))


def _load_local_preview(file_bytes, filename, sheet_name=None):
    return _load_dataframe(file_bytes, filename, sheet_name=sheet_name)


def _render_import_workflow(file_bytes, filename, ui_prefix, save_label):
    sheet_names = _get_sheet_names(file_bytes, filename)
    selected_sheet = sheet_names[0]
    if len(sheet_names) > 1:
        selected_sheet = st.selectbox(
            "Çalışma Sayfası Seç",
            sheet_names,
            key=f"{ui_prefix}_sheet_select",
        )
    df = _load_dataframe(file_bytes, filename, sheet_name=selected_sheet)
    st.write(
        f"**{filename}** — Toplam satır: {len(df)} | Toplam sütun: {len(df.columns)}"
    )
    st.dataframe(df.head(20))
    if df.empty:
        empty_state("Dosya boş", "Seçilen dosya veri içermiyor.")
        return

    mapping = _render_mapping_section(df, ui_prefix)
    rows = _build_import_rows(df, mapping)
    st.markdown("#### Veri Özeti")
    _preview_rows(rows)
    confirm = st.checkbox(
        "Önizlemeyi kontrol ettim ve aktarımı onaylıyorum.",
        key=f"{ui_prefix}_confirm",
    )
    if st.button(save_label, key=f"{ui_prefix}_save", disabled=not rows or not confirm):
        imported, skipped = _save_import_rows(rows)
        st.success(f"{imported} kayıt başarıyla aktarıldı.")
        if skipped:
            st.warning(
                f"{skipped} kayıt, aynı fatura numarası ve müşteri bilgisi nedeniyle atlandı."
            )


def render_drive_import():
    page_header(
        "Excel Veri Aktarımı",
        "Gelir-gider, rezervasyon, tahsilat veya fatura verilerini bilgisayarınızdan ya da Google Drive’dan içe aktarın.",
    )

    st.markdown(
        "Bu sayfada hem bilgisayardan Excel/CSV yükleyebilir hem de Google Drive'daki dosyaları seçerek verileri önizleyebilir ve aktarabilirsiniz."
    )

    st.markdown("---")
    st.subheader("Bilgisayardan Yükle")
    st.write("Bilgisayarınızdaki Excel veya CSV dosyasını seçerek verileri içe aktarın.")
    uploaded_file = st.file_uploader(
        "Dosya Seç",
        type=["xlsx", "xls", "csv"],
        key="local_excel_upload",
    )

    if uploaded_file is not None:
        filename = uploaded_file.name
        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            st.error("Desteklenen formatlar: XLSX, XLS, CSV")
        else:
            try:
                _render_import_workflow(
                    uploaded_file.getvalue(),
                    filename,
                    "local",
                    "Verileri Kaydet",
                )
            except Exception as exc:
                st.error(f"Dosya okunamadı veya işlenemedi: {exc}")

    st.markdown("---")
    section_header("Google Drive’dan Al", "Bağlı Google Drive klasöründeki Excel dosyalarını görüntüleyin ve içe aktarın.")

    initialize_drive_state()
    if not has_valid_drive_config():
        st.warning("Google Drive bağlantısı kurulmamış.")
        return
    if not st.session_state.gdrive_connected:
        st.info("Google Drive bilgileri hazır. Bağlantıyı Ayarlar sayfasından test edin.")
        return

    refresh_col, status_col = st.columns([1, 3])
    with refresh_col:
        refresh = st.button("Drive Dosyalarını Yenile", key="drive_refresh_files")
    if refresh:
        try:
            list_drive_files()
            st.success(f"{len(st.session_state.gdrive_files)} dosya bulundu.")
        except Exception as exc:
            st.session_state.gdrive_connected = False
            st.session_state.gdrive_connection_error = str(exc)
            st.error(f"Drive dosyaları yenilenemedi: {exc}")
            return
    with status_col:
        st.write(f"**{len(st.session_state.gdrive_files)} dosya hazır**")

    files = st.session_state.gdrive_files
    if not files:
        empty_state("Dosya bulunamadı", "Bağlı klasörde desteklenen Excel, CSV veya Google Sheets dosyası yok.")
        return

    search_term = st.text_input("Dosya ara", key="drive_file_search").strip().lower()
    filtered = [item for item in files if search_term in item.get("name", "").lower()]
    st.markdown("### Google Drive Dosyaları")
    st.caption(f"{len(filtered)} dosya gösteriliyor.")

    for item in filtered:
        file_id = item["id"]
        name = item.get("name", "Adsız dosya")
        modified = item.get("modifiedTime", "—")
        if modified != "—":
            try:
                modified = datetime.fromisoformat(modified.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
            except ValueError:
                pass
        info_col, preview_col, import_col = st.columns([6, 1, 1])
        with info_col:
            st.markdown(f"**{name}**")
            st.caption(
                f"{_format_drive_file_type(item.get('mimeType'))} • {modified} • {_human_readable_size(item.get('size'))}"
            )
        with preview_col:
            if st.button("Önizle", key=f"drive_preview_{file_id}"):
                st.session_state.gdrive_selected_file_id = file_id
        with import_col:
            if st.button("İçe Aktar", key=f"drive_import_{file_id}"):
                st.session_state.gdrive_selected_file_id = file_id

    selected_id = st.session_state.get("gdrive_selected_file_id")
    selected_file = next((item for item in files if item.get("id") == selected_id), None)
    if not selected_file:
        return

    st.markdown("---")
    st.subheader(f"{selected_file['name']} — Önizleme ve İçe Aktarma")
    try:
        service = get_drive_service()
        buffer = download_drive_file(
            selected_file["id"], selected_file["mimeType"], service=service
        )
        filename = selected_file["name"]
        if selected_file["mimeType"] == "application/vnd.google-apps.spreadsheet":
            filename = f"{Path(filename).stem}.xlsx"
        _render_import_workflow(
            buffer.getvalue(),
            filename,
            f"drive_{selected_file['id']}",
            "Drive'dan Verileri Kaydet",
        )
    except Exception as exc:
        st.error(f"Drive dosyası okunamadı veya işlenemedi: {exc}")
