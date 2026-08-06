import json
from pathlib import Path

import streamlit as st
from database.migrations import delete_demo_data, restore_demo_data
from services.google_drive_service import create_drive_service, list_drive_excel_files

LOCAL_CONFIG_PATH = Path(".streamlit/drive_local_secrets.json")


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


def _remove_local_config():
    if LOCAL_CONFIG_PATH.exists():
        LOCAL_CONFIG_PATH.unlink()


def _read_json_input(json_input):
    if not json_input:
        return None
    if isinstance(json_input, dict):
        return json_input
    try:
        return json.loads(json_input)
    except Exception:
        return None


def render_settings():
    st.header("Ayarlar")
    st.write("Uygulama ayarlarını ve Google Drive bağlantısını bu ekrandan yönetin.")

    local_config = _load_local_config()
    stored_json = local_config.get("service_account_json", "")
    stored_folder_id = local_config.get("folder_id", "")

    st.markdown("## Google Drive Bağlantısı")
    st.write(
        "Aşağıda Google Drive bağlantısını yerel olarak kaydedebilir veya Streamlit Cloud'da `st.secrets` üzerinden sağlayabilirsiniz."
    )

    col1, col2 = st.columns([3, 1], gap="large")
    with col1:
        drive_json_file = st.file_uploader(
            "Servis Hesabı JSON Yükle",
            type=["json"],
            help="Servis hesabı JSON dosyanızı seçin. Bu dosya yerel olarak `.streamlit/drive_local_secrets.json` içinde saklanacaktır.",
            key="settings_drive_json_file",
        )
        if drive_json_file is not None:
            try:
                uploaded_json = json.loads(drive_json_file.getvalue().decode("utf-8"))
                stored_json = uploaded_json
                st.success("Servis hesabı JSON başarıyla yüklendi.")
            except Exception:
                st.error("Geçerli bir JSON dosyası yükleyin.")

        drive_json_text = st.text_area(
            "Servis Hesabı JSON",
            value=json.dumps(stored_json, indent=2, ensure_ascii=False) if stored_json else "",
            height=220,
            key="settings_drive_json_text",
        )

        drive_folder_id = st.text_input(
            "Drive Klasör ID",
            value=stored_folder_id,
            help="Excel dosyalarınızın bulunduğu Google Drive klasörünün ID'sini girin.",
            key="settings_drive_folder_id",
        )

    with col2:
        st.markdown("#### Bağlantı Durumu")
        active = False
        service = None
        service_json = _read_json_input(drive_json_text)
        if service_json and drive_folder_id:
            try:
                service = create_drive_service(service_json)
                _ = list_drive_excel_files(drive_folder_id, service)
                active = True
                st.success("Google Drive bağlantısı aktif.")
            except Exception as exc:
                st.error(f"Bağlantı testi başarısız: {exc}")
        else:
            st.info("Servis hesabı JSON ve klasör ID gereklidir.")

        st.checkbox("Google Drive Bağlantısı Aktif", value=active, disabled=True)
        st.write("Streamlit Cloud ortamında servis hesabı bilgisi `st.secrets` üzerinden sağlanmalıdır.")

    if st.button("Bağlantıyı Test Et"):
        if not service_json:
            st.error("Önce geçerli bir JSON servis hesabı bilgisi girin.")
        elif not drive_folder_id:
            st.error("Önce klasör ID'sini girin.")
        else:
            try:
                service = create_drive_service(service_json)
                files = list_drive_excel_files(drive_folder_id, service)
                st.success(f"Bağlantı başarılı. Klasörde {len(files)} Excel dosyası bulundu.")
            except Exception as exc:
                st.error(f"Bağlantı testi başarısız: {exc}")

    save_col, remove_col = st.columns(2, gap="large")
    with save_col:
        if st.button("Bağlantıyı Kaydet"):
            if not service_json:
                st.error("Geçerli bir servis hesabı JSON bilgisi sağlayın.")
            elif not drive_folder_id:
                st.error("Drive Klasör ID'si gereklidir.")
            else:
                _save_local_config({"service_account_json": service_json, "folder_id": drive_folder_id})
                st.success("Google Drive bağlantısı yerel olarak kaydedildi.")
    with remove_col:
        if st.button("Bağlantıyı Kaldır"):
            _remove_local_config()
            st.success("Yerel Google Drive bağlantısı kaldırıldı.")

    st.markdown("---")
    st.write("Eğer Streamlit Cloud'da çalışıyorsanız, servis hesabı bilgilerini `st.secrets` içinde saklayın ve buraya yapıştırmayın.")

    st.markdown("## Demo Verisi Yönetimi")
    st.write("Demo verileri temizleyin veya yeniden yükleyin. Bu işlem yalnızca demo kayıtları etkiler.")

    with st.expander("Demo Verisi Yönetimi"):
        demo_col1, demo_col2 = st.columns(2)
        with demo_col1:
            if st.button("Demo Verilerini Sil"):
                deleted = delete_demo_data()
                st.success("Demo verileri silindi.")
                st.json(deleted)

        with demo_col2:
            if st.button("Demo Verilerini Geri Yükle"):
                restore_demo_data()
                st.success("Demo verileri yeniden yüklendi.")

        st.warning("Uyarı: Bu işlemler demo verisini etkiler, gerçek kayıtlarınızı silmez.")
