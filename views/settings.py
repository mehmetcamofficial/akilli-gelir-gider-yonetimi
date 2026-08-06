import streamlit as st
from database.migrations import delete_demo_data, restore_demo_data


def render_settings():
    st.header("Ayarlar")
    st.write("Demo verilerini kolayca yönetmek için aşağıdaki seçenekleri kullanın.")

    with st.expander("Demo Verisi Yönetimi"):
        st.write("Demo verileri temizleyin veya yeniden oluşturun. Bu işlem yalnızca demo kayıtları hedefler.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Demo Verilerini Sil"):
                deleted = delete_demo_data()
                st.success("Demo verileri silindi.")
                st.json(deleted)

        with col2:
            if st.button("Demo Verilerini Geri Yükle"):
                restore_demo_data()
                st.success("Demo verileri yeniden yüklendi.")

        st.warning("Uyarı: Bu işlemler demo verisini etkiler, gerçek kayıtlarınızı silmez.")
