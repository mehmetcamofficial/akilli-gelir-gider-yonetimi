import streamlit as st
from database.db import SessionLocal
from database.migrations import delete_demo_data, restore_demo_data
from database.models import AuditLog
from services.google_drive_config import (
    clear_drive_config,
    get_drive_folder_id,
    get_service_account_info,
    has_valid_drive_config,
    initialize_drive_state,
    list_drive_files,
    save_drive_config,
)
from views.drive_import import render_drive_file_list
from services.cache_service import reset_demo_runtime_state


def render_settings():
    st.header("Ayarlar")
    st.write("Uygulama ayarlarını ve Google Drive bağlantısını bu ekrandan yönetin.")

    initialize_drive_state()

    st.markdown("## Google Drive Bağlantısı")
    st.write(
        "Google Drive bağlantısını ayarlamak için servis hesabı JSON dosyanızı yükleyin, klasör ID'sini girin ve bağlantıyı test edin."
    )

    col1, col2, col3 = st.columns([3, 2, 2], gap="large")
    with col1:
        uploaded_file = st.file_uploader(
            "Servis Hesabı JSON Yükle",
            type=["json"],
            help="Servis hesabı JSON dosyanızı seçin. Bu dosya yalnızca oturumda tutulur ve GitHub'a yazılmaz.",
            key="settings_drive_json_file",
        )
        if uploaded_file is not None:
            try:
                save_drive_config(uploaded_file.getvalue().decode("utf-8"))
                st.success("Servis hesabı JSON başarıyla yüklendi.")
            except ValueError as exc:
                st.error(str(exc))

        if get_service_account_info():
            st.write("**JSON Yükleme Durumu:**")
            st.write("✓ JSON hazır")
        else:
            st.info("Servis hesabı JSON dosyası yükleyin veya Streamlit secrets üzerinden sağlayın.")

    with col2:
        folder_id_input = st.text_input(
            "Drive Klasör ID",
            value=get_drive_folder_id(),
            help="Excel dosyalarınızın bulunduğu Google Drive klasörünün ID'sini veya bağlantısını girin.",
            key="settings_drive_folder_id",
        )
        save_drive_config(folder_id=folder_id_input)

    with col3:
        st.markdown("#### Durum Paneli")
        current_json = get_service_account_info()
        folder_id = get_drive_folder_id()
        checks = []
        checks.append("✓ JSON hazır" if current_json else "✗ JSON eksik")
        checks.append("✓ Klasör ID girildi" if folder_id else "✗ Klasör ID eksik")
        checks.append("✓ Bağlantı başarılı" if st.session_state.gdrive_connected else "✗ Bağlantı henüz test edilmedi")
        if st.session_state.gdrive_files:
            checks.append(f"✓ {len(st.session_state.gdrive_files)} dosya bulundu")
        st.write("\n".join(checks))

    current_json = get_service_account_info()
    folder_id = get_drive_folder_id()

    if not current_json:
        st.warning("Google Drive bağlantısı kurulmamış.")
    elif not folder_id:
        st.info("Google Drive klasör ID girilmemiş.")
    elif not st.session_state.gdrive_connected:
        st.info("Google Drive bilgileri hazır. Bağlantıyı test edin.")
    else:
        st.success("Google Drive bağlantısı başarılı. Dosyalar Excel Veri Aktarımı sayfasında hazır." )

    connection_col1, connection_col2, connection_col3 = st.columns([2, 2, 2], gap="large")
    with connection_col1:
        if st.button("Bağlantıyı Test Et", disabled=not has_valid_drive_config()):
            try:
                files = list_drive_files()
                st.success(f"Bağlantı başarılı. {len(files)} dosya bulundu.")
            except Exception as exc:
                st.session_state.gdrive_connected = False
                st.session_state.gdrive_connection_error = str(exc)
                st.error(f"Bağlantı testi başarısız: {exc}")

    with connection_col2:
        if st.button("Drive Dosyalarını Yenile", disabled=not has_valid_drive_config()):
            try:
                files = list_drive_files()
                st.success(f"{len(files)} dosya bulundu.")
            except Exception as exc:
                st.session_state.gdrive_connected = False
                st.session_state.gdrive_connection_error = str(exc)
                st.error(f"Drive dosyaları yenilenemedi: {exc}")

    with connection_col3:
        if st.button("Bağlantıyı Temizle"):
            clear_drive_config()
            st.success("Oturumdaki Google Drive bağlantısı temizlendi.")

    with st.expander("Bağlantı Özeti", expanded=True):
        if st.session_state.gdrive_connected:
            st.write("✓ Bağlantı başarılı")
            st.write(f"Klasör ID: {folder_id}")
            st.write(f"Dosya sayısı: {len(st.session_state.gdrive_files)}")
            if st.session_state.gdrive_connection_error:
                st.write(f"Uyarı: {st.session_state.gdrive_connection_error}")
        elif st.session_state.gdrive_connection_error:
            st.write(f"Bağlantı testi başarısız: {st.session_state.gdrive_connection_error}")
        else:
            st.write("Henüz bağlantı testi yapılmadı.")

    if st.session_state.gdrive_connected:
        render_drive_file_list(key_prefix="settings_drive", show_import=True)

    st.markdown("---")
    st.write("Eğer Streamlit Cloud'da çalışıyorsanız, servis hesabı bilgilerini `st.secrets` içinde saklayın ve buraya yapıştırmayın.")

    st.markdown("## Demo Verisi Yönetimi")
    st.write("Demo verileri temizleyin veya yeniden yükleyin. Bu işlem yalnızca demo kayıtları etkiler.")

    with st.expander("Demo Verisi Yönetimi"):
        result = st.session_state.pop("demo_delete_result", None)
        if result is not None:
            if sum(result.values()):
                st.success("Demo verileri başarıyla silindi.")
                labels = {
                    "bookings": "Silinen rezervasyon",
                    "tours": "Silinen tur",
                    "customers": "Silinen müşteri",
                    "suppliers": "Silinen tedarikçi",
                    "transactions": "Silinen finans işlemi",
                    "collections": "Silinen tahsilat",
                    "supplier_payments": "Silinen ödeme",
                    "invoices": "Silinen fatura",
                    "documents": "Silinen belge",
                }
                columns = st.columns(4)
                for index, (key, label) in enumerate(labels.items()):
                    columns[index % 4].metric(label, result.get(key, 0))
            else:
                st.info("Silinecek demo verisi bulunamadı.")

        confirmed = st.checkbox(
            "Demo verilerinin silineceğini onaylıyorum",
            key="confirm_demo_delete",
        )
        demo_col1, demo_col2 = st.columns(2)
        with demo_col1:
            if st.button(
                "Demo Verilerini Kalıcı Olarak Sil",
                disabled=not confirmed,
                type="primary",
            ):
                deleted = delete_demo_data()
                audit_session = SessionLocal()
                try:
                    audit_session.add(AuditLog(event_type="demo_data_deleted", entity_type="demo_data", action="demo-data deletion", old_values=deleted, source="settings", status="Tamamlandı"))
                    audit_session.commit()
                finally:
                    audit_session.close()
                reset_demo_runtime_state()
                st.session_state.demo_delete_result = deleted
                st.rerun()

        with demo_col2:
            if st.button("Demo Verilerini Yükle"):
                restore_demo_data()
                reset_demo_runtime_state()
                st.success("Demo verileri yüklendi.")

        st.warning("Bu işlem geri alınamaz; gerçek kullanıcı kayıtları etkilenmez.")
