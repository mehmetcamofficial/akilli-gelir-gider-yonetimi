import streamlit as st
from sqlalchemy.orm import sessionmaker
from database.db import engine
from database.models import Document
import os


def show():
    st.header("Faturalar ve Belgeler")
    Session = sessionmaker(bind=engine)
    session = Session()

    docs = session.query(Document).order_by(Document.uploaded_at.desc()).limit(100).all()
    for d in docs:
        cols = st.columns([3,1])
        with cols[0]:
            st.markdown(f"**{d.original_filename}**  ")
            st.write(f"Yüklendi: {d.uploaded_at}")
            if d.file_path and os.path.exists(d.file_path):
                ext = d.original_filename.lower()
                if ext.endswith('.pdf'):
                    try:
                        import fitz
                        doc = fitz.open(d.file_path)
                        page = doc.load_page(0)
                        pix = page.get_pixmap(matrix=fitz.Matrix(2,2))
                        img_path = d.file_path + ".preview.png"
                        pix.save(img_path)
                        st.image(img_path, width=300)
                    except Exception:
                        st.write("PDF önizlemesi oluşturulamadı.")
                else:
                    st.image(d.file_path, width=300)
        with cols[1]:
            st.download_button("İndir", data=open(d.file_path, 'rb').read(), file_name=d.original_filename)

    session.close()
