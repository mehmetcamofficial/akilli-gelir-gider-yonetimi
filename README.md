# Gelir-Gider ve Akıllı Fatura Yönetim Sistemi

Bu repository, Streamlit tabanlı basit bir MVP uygulamasıdır.

Çalıştırma:

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Windows için:

```
.venv\Scripts\activate
streamlit run app.py
```

Streamlit Cloud deploy için:
- `app.py` ana dosyadır.
- `.streamlit/config.toml` zaten proje içinde yapılandırıldı.
- `st.secrets` kullanmak için dashboard üzerinde `drive_service_account_json` ve `drive_folder_id` değerlerini ekleyin.
- Alternatif olarak secrets dosyanızı aşağıdaki gibi oluşturabilirsiniz:

```toml
[drive]
drive_service_account_json = "<JSON servis hesabı verisi>"
drive_folder_id = "<Drive klasör ID'si>"
```

Yeni eklenen özellikler:
- Google Drive'dan Excel dosyalarını listeleme
- Drive dosyalarını önizleme, arama ve içe aktarma
- Muhasebe/finans kayıtlarına dönüşüm

Notlar:
- `database/app.db` dosyası ve `uploads/` klasörü `.gitignore` tarafından hariç tutulur.
- İlk çalıştırmada örnek demo verileri oluşturulur.
# akilli-gelir-gider-yonetimi
Streamlit tabanlı gelir-gider, fatura, stok ve kârlılık yönetim sistemi
