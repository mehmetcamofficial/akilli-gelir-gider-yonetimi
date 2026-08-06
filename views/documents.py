import os
import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Document


def render_documents():
    st.header("Belge Arşivi")
    Session = sessionmaker(bind=engine)
    session = Session()

    st.subheader("Yüklenen Dokümanlar")
    documents = session.query(Document).order_by(Document.uploaded_at.desc()).limit(200).all()
    if documents:
        for doc in documents:
            st.write(f"{doc.id} | {doc.original_filename} | {doc.file_type or '-'} | {doc.file_size or 0} byte | {doc.uploaded_at}")
            cols = st.columns([1,1,1])
            with cols[0]:
                if st.button(f"Dosya Yolu Göster {doc.id}", key=f'path_{doc.id}'):
                    st.write(doc.file_path or "-")
            with cols[1]:
                if st.button(f"Sil {doc.id}", key=f'del_{doc.id}'):
                    if doc.file_path and os.path.exists(doc.file_path):
                        try:
                            os.remove(doc.file_path)
                        except Exception:
                            pass
                    session.delete(doc)
                    session.commit()
                    st.success("Belge silindi.")
                    st.experimental_rerun()
            with cols[2]:
                if st.button(f"Tekrar Yükle {doc.id}", key=f'reload_{doc.id}'):
                    st.warning("Belge yeniden yükleme özelliği henüz desteklenmiyor.")
    else:
        st.info("Henüz belge yüklenmemiş.")

    session.close()
