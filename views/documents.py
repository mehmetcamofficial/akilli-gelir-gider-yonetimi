import os
import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Document
from utils.ui import page_header, section_header, format_date, empty_state


def render_documents():
    page_header(
        "Belge Arşivi",
        "Finans ve operasyon belgelerinizi kaydedin, inceleyin ve yönetin.",
    )

    Session = sessionmaker(bind=engine)
    session = Session()
    documents = session.query(Document).order_by(Document.uploaded_at.desc()).limit(200).all()

    if not documents:
        empty_state(
            "Belge bulunamadı",
            "Sisteminize eklenmiş belge kaydı yok. Belgeleri yükleyerek arşivleyebilirsiniz.",
        )
        session.close()
        return

    section_header("Yüklenen Dokümanlar")
    st.markdown("<div class='table-container'>", unsafe_allow_html=True)
    st.markdown(
        "<table><thead><tr><th>ID</th><th>Dosya Adı</th><th>Tür</th><th>Boyut</th><th>Yüklendi</th><th>İşlemler</th></tr></thead><tbody>",
        unsafe_allow_html=True,
    )
    for doc in documents:
        st.markdown(
            f"<tr><td>{doc.id}</td>"
            f"<td>{doc.original_filename or 'Bilinmiyor'}</td>"
            f"<td>{doc.file_type or '-'}</td>"
            f"<td>{doc.file_size or 0} byte</td>"
            f"<td>{format_date(doc.uploaded_at) if doc.uploaded_at else '-'}</td>"
            f"<td>{'Sil / Göster'}</td></tr>",
            unsafe_allow_html=True,
        )
    st.markdown("</tbody></table>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    for doc in documents:
        cols = st.columns([3, 1, 1])
        with cols[0]:
            st.write(f"**{doc.original_filename or 'Bilinmiyor'}**")
            st.write(f"Tür: {doc.file_type or '-'}")
            st.write(f"Boyut: {doc.file_size or 0} byte")
            st.write(f"Yükleme: {format_date(doc.uploaded_at) if doc.uploaded_at else '-'}")
        with cols[1]:
            if st.button(f"Yolu Göster {doc.id}", key=f'path_{doc.id}'):
                st.write(doc.file_path or "-")
        with cols[2]:
            if st.button(f"Sil {doc.id}", key=f'del_{doc.id}'):
                if doc.file_path and os.path.exists(doc.file_path):
                    try:
                        os.remove(doc.file_path)
                    except Exception:
                        pass
                session.delete(doc)
                session.commit()
                st.success("Belge silindi.")
                st.rerun()
    session.close()
