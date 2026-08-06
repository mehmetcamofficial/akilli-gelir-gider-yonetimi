import json
import os
from io import BytesIO
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Transaction, Booking
from services.google_drive_service import create_drive_service, list_drive_excel_files, download_drive_file
from services.drive_import_service import normalize_dataframe, normalize_column_name, parse_decimal, parse_date
from utils.ui import page_header, section_header, empty_state

LOCAL_CONFIG_PATH = Path(".streamlit/drive_local_secrets.json")
SUPPORTED_EXTENSIONS = [".xlsx", ".xls", ".csv"]
FIELD_ORDER = [
    ("transaction_date", "Tarih"),
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


def _extract_folder_id(value):
    if not value:
        return ""
    if "folders/" in value:
        value = value.split("folders/")[-1].split("?")[0].strip()
    return value.strip()


def _read_service_account_json(secret_value):
    if not secret_value:
        return None
    if isinstance(secret_value, dict):
        return secret_value
    try:
        return json.loads(secret_value)
    except Exception:
        return None


def _load_local_config():
    if LOCAL_CONFIG_PATH.exists():
        try:
            return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_local_config(config):
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def _find_drive_secret():
    drive_block = {}
    try:
        drive_block = st.secrets.get("drive", {}) or {}
    except Exception:
        drive_block = {}

    local_config = _load_local_config()
    service_json = (
        st.secrets.get("gcp_service_account")
        or st.secrets.get("drive_service_account_json")
        or drive_block.get("drive_service_account_json")
        or drive_block.get("service_account_json")
        or local_config.get("service_account_json", "")
    )
    folder_id = (
        st.secrets.get("drive_folder_id")
        or drive_block.get("drive_folder_id", "")
        or local_config.get("folder_id", "")
    )

    return {
        "service_account_json": service_json,
        "folder_id": folder_id,
    }


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
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            st.error("Desteklenen formatlar: XLSX, XLS, CSV")
        else:
            file_bytes = uploaded_file.getvalue()
            try:
                sheet_names = _get_sheet_names(file_bytes, filename)
                selected_sheet = sheet_names[0] if len(sheet_names) == 1 else st.selectbox("Çalışma Sayfası Seç", sheet_names, key="local_sheet_select")
                df = _load_dataframe(file_bytes, filename, sheet_name=selected_sheet)
                st.write(f"**{filename}** yüklendi. Toplam satır: {len(df)} | Toplam sütun: {len(df.columns)}")
                st.dataframe(df.head(20))

                if df.empty:
                    empty_state("Dosya boş", "Seçilen dosya veri içermiyor.")
                else:
                    mapping = _render_mapping_section(df, "local")
                    rows = _build_import_rows(df, mapping)
                    st.markdown("#### Veri Özeti")
                    _preview_rows(rows)
                    if st.button("Verileri Kaydet", key="local_save_data"):
                        if not rows:
                            st.warning("Veritabanına aktarım için geçerli veri bulunamadı.")
                        else:
                            session = sessionmaker(bind=engine)()
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
                                    booking = session.query(Booking).filter(Booking.booking_number == raw["booking_number"]).first()
                                    if booking:
                                        txn.description = (
                                            f"{txn.description or ''} | Rezervasyon: {booking.booking_number}".strip(' | ')
                                        )
                                session.add(txn)
                                imported += 1
                            session.commit()
                            session.close()
                            st.success(f"{imported} kayıt başarıyla aktarıldı.")
                            if skipped:
                                st.warning(f"{skipped} kayıt, aynı fatura numarası ve müşteri bilgisi nedeniyle atlandı.")
            except Exception as exc:
                st.error(f"Dosya okunamadı veya işlenemedi: {exc}")

    st.markdown("---")
    section_header("Google Drive’dan Al", "Bağlı Google Drive klasöründeki Excel dosyalarını görüntüleyin ve içe aktarın.")

    secrets = _find_drive_secret()
    account_info = _read_service_account_json(secrets["service_account_json"])
    folder_id = _extract_folder_id(secrets["folder_id"])
    service = None
    files = []

    if account_info and folder_id:
        try:
            service = create_drive_service(account_info)
        except Exception as exc:
            st.warning(f"Drive bağlantısı başlatılamadı: {exc}")

    if service is None:
        st.warning(
            "Drive dosyalarını kullanmak için Ayarlar sayfasında Google Drive servis hesabı JSON ve klasör ID girin."
        )
    else:
        if st.button("Drive Dosyalarını Göster", key="drive_show_files"):
            try:
                files = list_drive_excel_files(folder_id, service)
                st.session_state.drive_files = files
                st.success(f"{len(files)} dosya bulundu.")
            except Exception as exc:
                st.error(f"Drive dosyaları listelenemedi: {exc}")
        files = st.session_state.get("drive_files", [])

        if files:
            search_term = st.text_input("Dosya ara", key="drive_file_search")
            filtered = [f for f in files if search_term.lower() in f["name"].lower()] if search_term else files
            st.write(f"{len(filtered)} dosya gösteriliyor.")
            selected_file = st.selectbox(
                "Aktarılacak dosyayı seçin",
                filtered,
                format_func=lambda f: f["name"],
                key="drive_selected_file",
            )
        else:
            selected_file = None

        if selected_file:
            with st.expander(f"{selected_file['name']} önizlemesi", expanded=True):
                try:
                    buffer = download_drive_file(selected_file["id"], selected_file["mimeType"], service)
                    bytes_data = buffer.getvalue()
                    sheet_names = _get_sheet_names(bytes_data, selected_file["name"])
                    selected_sheet = sheet_names[0] if len(sheet_names) == 1 else st.selectbox("Çalışma Sayfası Seç", sheet_names, key="drive_sheet_select")
                    df = _load_dataframe(bytes_data, selected_file["name"], sheet_name=selected_sheet)
                    st.dataframe(df.head(20))
                    if df.empty:
                        empty_state("Dosya boş", "Seçilen Drive dosyasında veri bulunamadı.")
                    else:
                        mapping = _render_mapping_section(df, "drive")
                        rows = _build_import_rows(df, mapping)
                        st.markdown("#### Veri Özeti")
                        _preview_rows(rows)
                        if st.button("Drive'dan Verileri Kaydet", key="drive_save_data"):
                            if not rows:
                                st.warning("Veritabanına aktarım için geçerli veri bulunamadı.")
                            else:
                                session = sessionmaker(bind=engine)()
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
                                        booking = session.query(Booking).filter(Booking.booking_number == raw["booking_number"]).first()
                                        if booking:
                                            txn.description = (
                                                f"{txn.description or ''} | Rezervasyon: {booking.booking_number}".strip(' | ')
                                            )
                                    session.add(txn)
                                    imported += 1
                                session.commit()
                                session.close()
                                st.success(f"{imported} kayıt başarıyla aktarıldı.")
                                if skipped:
                                    st.warning(f"{skipped} kayıt, aynı fatura numarası ve müşteri bilgisi nedeniyle atlandı.")
                except Exception as exc:
                    st.error(f"Drive dosyası okunamadı veya işlenemedi: {exc}")
