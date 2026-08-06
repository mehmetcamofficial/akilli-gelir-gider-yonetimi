import json
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Transaction, Booking
from services.google_drive_service import create_drive_service, list_drive_excel_files, download_drive_file
from services.drive_import_service import normalize_dataframe
from utils.ui import page_header, format_currency


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


def _find_drive_secret():
    drive_block = {}
    try:
        drive_block = st.secrets.get("drive", {}) or {}
    except Exception:
        drive_block = {}

    return {
        "service_account_json": st.secrets.get("drive_service_account_json", "") or drive_block.get("drive_service_account_json", "") or drive_block.get("service_account_json", ""),
        "folder_id": st.secrets.get("drive_folder_id", "") or drive_block.get("drive_folder_id", ""),
    }


def render_drive_import():
    page_header(
        "Drive Excel Aktarımı",
        "Muhasebe ve finans Excel dosyalarınızı Google Drive'dan çekin, önizleyin, arayın ve hızlıca finans kayıtlarına aktarın.",
    )

    secrets = _find_drive_secret()
    st.markdown(
        "Google Drive bağlantısı için servis hesabı JSON'unuzu ve Excel dosya klasörü ID'sini girin. Streamlit Cloud'da bu bilgileri `st.secrets` içinde saklayın."
    )

    with st.expander("Drive Bağlantı Ayarları", expanded=True):
        drive_secret = st.text_area(
            "Servis Hesabı JSON",
            value=secrets["service_account_json"],
            help="Drive API erişimi için servis hesabı JSON'unuzu buraya yapıştırın veya Streamlit secrets içinde saklayın.",
            height=220,
            key="drive_service_json_input",
        )
        drive_folder_id = st.text_input(
            "Drive Klasör ID'si",
            value=secrets["folder_id"],
            help="Excel dosyalarınızın bulunduğu klasörün ID'sini girin.",
            key="drive_folder_id_input",
        )
        if st.button("Drive Bağlantısını Test Et"):
            try:
                account_info = _read_service_account_json(drive_secret)
                if account_info is None:
                    st.error("Geçerli bir JSON servis hesabı bilgisi sağlayın.")
                else:
                    folder_id = _extract_folder_id(drive_folder_id)
                    service = create_drive_service(account_info)
                    files = list_drive_excel_files(folder_id, service)
                    st.success(f"Bağlantı sağlandı. Klasörde {len(files)} dosya bulundu.")
            except Exception as exc:
                st.error(f"Drive bağlantısı kurulamadı: {exc}")

    if "drive_service_json" not in st.session_state:
        st.session_state.drive_service_json = drive_secret
    if "drive_folder_id" not in st.session_state:
        st.session_state.drive_folder_id = drive_folder_id

    try:
        account_info = _read_service_account_json(st.session_state.drive_service_json)
        folder_id = _extract_folder_id(st.session_state.drive_folder_id)
        service = create_drive_service(account_info) if account_info and folder_id else None
    except Exception as exc:
        service = None
        st.error(f"Drive servisi başlatılamadı: {exc}")

    if service is None:
        st.warning("Drive bağlantısı hazır değil. Lütfen servis hesabı JSON'unuzu ve klasör ID'sini girin.")
        return

    with st.expander("Drive Dosyalarını Listele"):
        try:
            files = list_drive_excel_files(folder_id, service)
            search_term = st.text_input("Dosya ara", key="drive_file_search")
            filtered = [f for f in files if search_term.lower() in f["name"].lower()] if search_term else files
            st.write(f"{len(filtered)} Excel dosyası bulundu.")
            for file in filtered:
                st.markdown(
                    f"- **{file['name']}** ({file['mimeType']}) — {file.get('size', '?-')} byte — güncellendi: {file.get('modifiedTime', '-')}")
            if filtered:
                selected_file = st.selectbox(
                    "Aktarılacak dosyayı seçin",
                    filtered,
                    format_func=lambda f: f["name"],
                    key="drive_selected_file",
                )
            else:
                selected_file = None
        except Exception as exc:
            st.error(f"Drive dosyaları listelenemedi: {exc}")
            return

    if selected_file:
        with st.expander(f"{selected_file['name']} önizlemesi", expanded=True):
            try:
                buffer = download_drive_file(selected_file["id"], selected_file["mimeType"], service)
                df = pd.read_excel(buffer, engine="openpyxl")
                if df.empty:
                    st.warning("Seçilen dosya boş.")
                    return
                st.write("İlk 20 satır önizleme:")
                st.dataframe(df.head(20))

                search_data = st.text_input("Önizlemeyi içeriğe göre ara", key="drive_preview_search")
                if search_data:
                    mask = df.astype(str).apply(lambda row: row.str.contains(search_data, case=False, na=False)).any(axis=1)
                    st.dataframe(df[mask].head(20))

                if st.button("Bu Excel'i Finans Kayıtlarına Aktar", key="import_drive_excel"):
                    normalized = normalize_dataframe(df)
                    if not normalized:
                        st.warning("Dosya yapısı tanınamadı veya veri bulunamadı.")
                        return

                    session = sessionmaker(bind=engine)()
                    imported = []
                    skipped = []
                    for row in normalized:
                        existing = None
                        if row.get("invoice_number"):
                            existing = session.query(Transaction).filter(
                                Transaction.invoice_number == row["invoice_number"],
                                Transaction.party_name == row.get("party_name"),
                            ).first()
                        if existing:
                            skipped.append(row)
                            continue

                        txn = Transaction(
                            transaction_type=row.get("transaction_type", "income"),
                            transaction_date=row.get("transaction_date") or datetime.utcnow(),
                            due_date=row.get("due_date"),
                            invoice_number=row.get("invoice_number") or None,
                            description=row.get("description") or f"Drive aktarılan kayıt: {selected_file['name']}",
                            party_name=row.get("party_name") or None,
                            currency="TRY",
                            subtotal=row.get("subtotal", 0),
                            tax_total=row.get("tax_total", 0),
                            grand_total=row.get("grand_total", 0),
                            paid_amount=0,
                            remaining_amount=row.get("grand_total", 0),
                            payment_status=row.get("payment_status", "Ödenmedi"),
                            invoice_type="sale" if row.get("transaction_type") == "income" else "purchase",
                        )
                        if row.get("booking_number"):
                            booking = session.query(Booking).filter(Booking.booking_number == row["booking_number"]).first()
                            if booking:
                                txn.description += f" | Rezervasyon: {booking.booking_number}"

                        session.add(txn)
                        imported.append(row)

                    session.commit()
                    session.close()

                    st.success(f"{len(imported)} satır aktarıldı, {len(skipped)} satır atlandı.")
                    if skipped:
                        st.warning("Aynı fatura numarası ve müşteri adına sahip kayıtlar tekrar eklenmedi.")
            except Exception as exc:
                st.error(f"Dosya indirilemedi veya okunamadı: {exc}")
