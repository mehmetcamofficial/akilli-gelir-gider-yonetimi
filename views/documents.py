from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from database.db import SessionLocal
from database.models import AuditLog, Document
from services.storage_service import delete_document_content, load_document_bytes, store_document_bytes
from utils.ui import empty_state, format_date, page_header, section_header


SUPPORTED_TYPES = ["pdf", "jpg", "jpeg", "png", "xlsx", "xls", "csv"]


def _preview(document, content):
    suffix = Path(document.original_filename or "").suffix.lower()
    if suffix == ".pdf":
        if hasattr(st, "pdf"):
            st.pdf(content, height=700)
        else:
            st.info("PDF önizlemesi bu Streamlit sürümünde desteklenmiyor; İndir düğmesini kullanın.")
    elif suffix in {".jpg", ".jpeg", ".png"}:
        st.image(content, use_container_width=True)
    elif suffix == ".csv":
        st.dataframe(pd.read_csv(BytesIO(content)).head(100), use_container_width=True)
    elif suffix in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(BytesIO(content), engine="xlrd" if suffix == ".xls" else "openpyxl")
        sheet = st.selectbox("Çalışma sayfası", workbook.sheet_names, key=f"archive_sheet_{document.id}")
        st.dataframe(pd.read_excel(BytesIO(content), sheet_name=sheet).head(100), use_container_width=True)
    else:
        st.info("Bu dosya türü doğrudan önizlenemiyor; dosyayı indirebilirsiniz.")


def _clear_archive_state(document_id=None):
    for key in list(st.session_state):
        if key.startswith("archive_") and (document_id is None or str(document_id) in key):
            st.session_state.pop(key, None)


def render_documents():
    page_header("Belge Arşivi", "Belgeleri Google Drive’da kalıcı olarak saklayın, önizleyin ve indirin.")
    session = SessionLocal()
    try:
        section_header("Yeni Belge Yükle")
        uploaded = st.file_uploader("PDF, görsel, Excel veya CSV seçin", type=SUPPORTED_TYPES, key="archive_upload")
        if uploaded and st.button("Belgeyi Drive’a Kaydet", type="primary"):
            try:
                document, duplicate = store_document_bytes(uploaded.getvalue(), uploaded.name, uploaded.type, session)
                if duplicate:
                    st.warning(f"Aynı SHA-256 değerine sahip belge zaten mevcut: Belge #{document.id}")
                else:
                    st.success(f"Belge kalıcı olarak kaydedildi. Belge #{document.id}")
                    _clear_archive_state()
                    st.rerun()
            except Exception as exc:
                session.rollback()
                st.error(f"Belge kaydedilemedi: {exc}")

        documents = session.query(Document).order_by(Document.uploaded_at.desc()).limit(500).all()
        if not documents:
            empty_state("Belge bulunamadı", "Arşive belge yüklediğinizde burada görüntülenecek.")
            return

        section_header("Arşiv Belgeleri")
        search = st.text_input("Belge ara", key="archive_search").strip().casefold()
        visible = [document for document in documents if search in (document.original_filename or "").casefold()]
        for document in visible:
            with st.container(border=True):
                info, preview_col, download_col, delete_col = st.columns([5, 1, 1, 1])
                with info:
                    st.markdown(f"**{document.original_filename or 'Adsız belge'}**")
                    st.caption(
                        f"#{document.id} · {document.file_type or 'Bilinmeyen tür'} · {document.file_size or 0:,} byte · "
                        f"{format_date(document.uploaded_at) if document.uploaded_at else '—'} · "
                        f"Depolama: {'Google Drive' if document.drive_file_id else 'Yerel geliştirme'}"
                    )
                    st.code(f"SHA-256: {document.file_hash or '—'}", language=None)
                with preview_col:
                    if st.button("Önizle", key=f"archive_preview_button_{document.id}"):
                        st.session_state.archive_preview_id = document.id
                with download_col:
                    if st.button("İndir", key=f"archive_download_prepare_{document.id}"):
                        try:
                            st.session_state[f"archive_download_{document.id}"] = load_document_bytes(document)
                        except Exception as exc:
                            st.error(f"Dosya alınamadı: {exc}")
                with delete_col:
                    if st.button("Sil", key=f"archive_delete_{document.id}"):
                        try:
                            deleted_values = {"filename": document.original_filename, "file_hash": document.file_hash, "storage_provider": document.storage_provider, "drive_file_id": document.drive_file_id}
                            delete_document_content(document)
                            session.add(AuditLog(event_type="document_deleted", entity_type="document", entity_id=document.id, action="document_deletion", old_values=deleted_values, source="document_archive", status="Tamamlandı"))
                            session.delete(document)
                            session.commit()
                            _clear_archive_state(document.id)
                            st.success("Belge Drive ve PostgreSQL’den silindi.")
                            st.rerun()
                        except Exception as exc:
                            session.rollback()
                            st.error(f"Belge silinemedi: {exc}")
                prepared = st.session_state.get(f"archive_download_{document.id}")
                if prepared is not None:
                    st.download_button("Dosyayı Kaydet", prepared, document.original_filename or "belge", document.file_type or "application/octet-stream", key=f"archive_download_ready_{document.id}")
                if document.drive_web_view_link:
                    st.link_button("Google Drive’da Aç", document.drive_web_view_link)

        selected_id = st.session_state.get("archive_preview_id")
        selected = next((document for document in visible if document.id == selected_id), None)
        if selected:
            st.markdown("---")
            st.subheader(f"Önizleme: {selected.original_filename}")
            try:
                _preview(selected, load_document_bytes(selected))
            except Exception as exc:
                st.error(f"Önizleme yüklenemedi: {exc}")
    finally:
        session.close()
