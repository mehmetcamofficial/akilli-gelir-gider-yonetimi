import hashlib
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy.orm import sessionmaker

from database.db import engine
from services.drive_import_service import (
    DATASET_TYPES,
    REQUIRED_FIELDS,
    TARGET_FIELDS,
    AIColumnLabelingService,
    ColumnMappingService,
    DatasetTypeClassifier,
    ExcelFileReader,
    ImportExecutionService,
    RowValidationService,
    ValueNormalizationService,
)
from services.google_drive_config import (
    download_drive_file,
    has_valid_drive_config,
    initialize_drive_state,
    list_drive_files,
)
from services.google_drive_service import ALLOWED_MIME_TYPES
from utils.ui import empty_state, page_header, section_header


SUPPORTED_EXTENSIONS = [".xlsx", ".xls", ".csv"]
Session = sessionmaker(bind=engine)


def _format_drive_file_type(mime_type):
    return {
        "application/vnd.google-apps.spreadsheet": "Google Sheets",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
        "application/vnd.ms-excel": "XLS",
        "text/csv": "CSV",
    }.get(mime_type, mime_type)


def _human_readable_size(size):
    if not size:
        return "—"
    try:
        size = int(size)
    except (TypeError, ValueError):
        return str(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _data_type_label(series):
    values = series.dropna()
    if values.empty:
        return "Boş"
    numeric = pd.to_numeric(values, errors="coerce").notna().mean()
    dates = pd.to_datetime(values, errors="coerce", dayfirst=True).notna().mean()
    if numeric >= 0.8:
        return "Sayı"
    if dates >= 0.8:
        return "Tarih"
    if numeric > 0.15 or dates > 0.15:
        return "Karışık"
    return "Metin"


def _quality_messages(df):
    messages = []
    empty_cells = int(df.isna().sum().sum())
    if empty_cells:
        messages.append(f"{empty_cells} boş hücre bulundu.")
    duplicates = int(df.duplicated().sum())
    if duplicates:
        messages.append(f"{duplicates} tamamen aynı satır bulundu.")
    mixed = [column for column in df.columns if _data_type_label(df[column]) == "Karışık"]
    if mixed:
        messages.append("Karışık veri türü olan kolonlar: " + ", ".join(mixed))
    return messages or ["Belirgin bir veri kalitesi sorunu bulunmadı."]


def _excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sonuç")
    return output.getvalue()


def _analysis_key(prefix):
    return f"{prefix}_smart_import_analysis"


def _render_import_workflow(file_bytes, filename, ui_prefix, save_label=None):
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    st.markdown("#### 1. Dosyayı Seç → 2. Dosyayı Analiz Et → 3. Kolonları Eşleştir → 4. Veriyi Doğrula → 5. İçe Aktar")
    sheets = ExcelFileReader.sheet_names(file_bytes, filename)
    selected_sheet = st.selectbox("Çalışma sayfası", sheets, key=f"{ui_prefix}_sheet") if len(sheets) > 1 else sheets[0]

    analyze_clicked = st.button("Dosyayı Analiz Et", key=f"{ui_prefix}_analyze", type="primary")
    cached = st.session_state.get(_analysis_key(ui_prefix))
    if analyze_clicked or not cached or cached.get("hash") != file_hash or cached.get("sheet") != selected_sheet:
        try:
            df, header_index = ExcelFileReader.analyze(file_bytes, filename, selected_sheet)
            mapping_analysis = ColumnMappingService.analyze(df.columns)
            detected_type, type_confidence = DatasetTypeClassifier.classify(mapping_analysis)
            cached = {
                "hash": file_hash, "sheet": selected_sheet, "df": df,
                "header_index": header_index, "mapping": mapping_analysis,
                "dataset_type": detected_type, "type_confidence": type_confidence,
            }
            st.session_state[_analysis_key(ui_prefix)] = cached
        except Exception as exc:
            st.error(f"Dosya analiz edilemedi: {exc}")
            return

    df = cached["df"]
    if df.empty:
        empty_state("Dosya boş", "Başlık satırından sonra aktarılabilir veri bulunamadı.")
        return

    st.success(f"Başlık satırı otomatik olarak {cached['header_index'] + 1}. satırda bulundu.")
    col1, col2, col3 = st.columns(3)
    col1.metric("Veri satırı", len(df))
    col2.metric("Kolon", len(df.columns))
    col3.metric("Dosya türü", Path(filename).suffix.upper().lstrip("."))
    st.dataframe(df.head(20), use_container_width=True)
    with st.expander("Kolon türleri ve veri kalitesi", expanded=True):
        st.dataframe(pd.DataFrame({"Kolon": df.columns, "Algılanan Tür": [_data_type_label(df[c]) for c in df.columns]}), hide_index=True)
        for message in _quality_messages(df):
            st.info(message)

    st.markdown("#### 3. Kolonları Eşleştir")
    st.info(f"Algılanan veri türü: **{cached['dataset_type']}** · Güven: %{cached['type_confidence'] * 100:.0f}")
    default_index = DATASET_TYPES.index(cached["dataset_type"])
    dataset_type = st.selectbox("Veri türü (gerekirse düzeltin)", DATASET_TYPES, index=default_index, key=f"{ui_prefix}_dataset_type")

    mapping_state_key = f"{ui_prefix}_mapping"
    if st.button("Kolonları Otomatik Eşleştir", key=f"{ui_prefix}_automap"):
        chosen = set()
        mapping = {}
        ranked = sorted(cached["mapping"].items(), key=lambda item: item[1]["confidence"], reverse=True)
        for source, info in ranked:
            target = info["target"] if info["confidence"] >= 0.72 and info["target"] not in chosen else "Kullanma"
            mapping[source] = target
            if target != "Kullanma":
                chosen.add(target)
        st.session_state[mapping_state_key] = mapping
        for source, target in mapping.items():
            st.session_state[f"{ui_prefix}_map_{source}"] = target

    if st.button("Eşleştirmeyi Sıfırla", key=f"{ui_prefix}_reset"):
        st.session_state[mapping_state_key] = {str(c): "Kullanma" for c in df.columns}
        for source in df.columns:
            st.session_state[f"{ui_prefix}_map_{source}"] = "Kullanma"

    mapping = st.session_state.get(mapping_state_key)
    if mapping is None:
        mapping, chosen = {}, set()
        for source, info in sorted(cached["mapping"].items(), key=lambda item: item[1]["confidence"], reverse=True):
            target = info["target"] if info["confidence"] >= 0.72 and info["target"] not in chosen else "Kullanma"
            mapping[source] = target
            if target != "Kullanma": chosen.add(target)
        st.session_state[mapping_state_key] = mapping

    ambiguous_columns = [source for source, info in cached["mapping"].items() if info["confidence"] < 0.72]
    try:
        openrouter_key = st.secrets.get("OPENROUTER_API_KEY")
    except Exception:
        openrouter_key = None
    if openrouter_key and ambiguous_columns:
        if st.button("Belirsiz Kolonlar İçin AI Önerisi Al", key=f"{ui_prefix}_ai_columns"):
            try:
                st.session_state[f"{ui_prefix}_ai_suggestions"] = AIColumnLabelingService.suggest(openrouter_key, df, ambiguous_columns)
            except Exception as exc:
                st.warning(f"AI önerisi alınamadı; manuel eşleştirmeye devam edebilirsiniz: {exc}")
        suggestions = st.session_state.get(f"{ui_prefix}_ai_suggestions")
        if suggestions:
            st.caption("AI önerileri yalnızca bilgilendirme amaçlıdır; seçimleri kullanıcı yapar.")
            st.dataframe(pd.DataFrame(suggestions), hide_index=True, use_container_width=True)

    options = ["Kullanma"] + list(TARGET_FIELDS)
    rows = []
    for source in df.columns:
        info = cached["mapping"].get(str(source), {"target": None, "confidence": 0})
        current = mapping.get(str(source), "Kullanma")
        selected = st.selectbox(
            f"Kaynak: {source}", options, index=options.index(current) if current in options else 0,
            format_func=lambda value: "Kullanma" if value == "Kullanma" else TARGET_FIELDS[value],
            key=f"{ui_prefix}_map_{source}",
        )
        mapping[str(source)] = selected
        confidence = info["confidence"] if selected == info["target"] else 0
        rows.append({"Kaynak Kolon": source, "Hedef Alan": "—" if selected == "Kullanma" else TARGET_FIELDS[selected], "Güven": f"%{confidence * 100:.0f}", "Durum": "Eşleşti" if confidence >= .85 else ("Kontrol Edin" if selected != "Kullanma" else "Eşleşmedi")})
    st.session_state[mapping_state_key] = mapping
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    selected_targets = [value for value in mapping.values() if value != "Kullanma"]
    duplicates = sorted({value for value in selected_targets if selected_targets.count(value) > 1})
    missing = REQUIRED_FIELDS.get(dataset_type, set()) - set(selected_targets)
    if duplicates:
        st.error("Bir hedef alana birden fazla kolon bağlanamaz: " + ", ".join(TARGET_FIELDS[x] for x in duplicates))
    if missing:
        st.error("Zorunlu alanlar eksik: " + ", ".join(TARGET_FIELDS[x] for x in sorted(missing)))

    st.markdown("#### 4. Veriyi Doğrula")
    if st.button("Önizlemeyi Yenile", key=f"{ui_prefix}_refresh_preview"):
        st.session_state.pop(f"{ui_prefix}_validation", None)
    validation_key = f"{ui_prefix}_validation"
    signature = json.dumps({"mapping": mapping, "type": dataset_type}, sort_keys=True, ensure_ascii=False)
    validation_cache = st.session_state.get(validation_key)
    if not validation_cache or validation_cache["signature"] != signature:
        session = Session()
        try:
            validated = []
            for _, source_row in df.iterrows():
                normalized = ValueNormalizationService.row(source_row, mapping)
                validated.append({"row": normalized, "validation": RowValidationService.validate(session, dataset_type, normalized)})
        finally:
            session.close()
        validation_cache = {"signature": signature, "rows": validated}
        st.session_state[validation_key] = validation_cache
    validated = validation_cache["rows"]
    counts = {status: sum(item["validation"]["status"] == status for item in validated) for status in ["Hazır", "Uyarılı", "Hatalı", "Mükerrer"]}
    metrics = st.columns(5)
    metrics[0].metric("Toplam", len(validated))
    for index, status in enumerate(["Hazır", "Uyarılı", "Hatalı", "Mükerrer"], 1):
        metrics[index].metric(status, counts[status])

    preview = []
    for index, item in enumerate(validated, 1):
        preview.append({"Satır": index, **item["row"], "Aktarım Durumu": item["validation"]["status"], "Hata Mesajı": "; ".join(item["validation"]["messages"]), "Eşleşen Kayıt": item["validation"].get("matched_record") or ("Mevcut kayıt" if item["validation"]["duplicate"] else "—"), "Mükerrer Durumu": item["validation"]["duplicate"] or "Yeni"})
    preview_df = pd.DataFrame(preview)
    status_filter = st.selectbox("Duruma göre filtrele", ["Tümü", "Hazır", "Uyarılı", "Hatalı", "Mükerrer"], key=f"{ui_prefix}_status_filter")
    visible = preview_df if status_filter == "Tümü" else preview_df[preview_df["Aktarım Durumu"] == status_filter]
    st.dataframe(visible, use_container_width=True, hide_index=True)

    error_df = preview_df[preview_df["Aktarım Durumu"].isin(["Hatalı", "Mükerrer"])]
    if not error_df.empty:
        st.download_button("Hatalı Satırları İndir", _excel_bytes(error_df), "hatali_satirlar.xlsx", key=f"{ui_prefix}_errors_download")

    st.markdown("#### 5. İçe Aktar")
    include_duplicates = st.checkbox("Mükerrer görünen satırları da aktar", key=f"{ui_prefix}_include_duplicates")
    confirmed = st.checkbox("Doğrulama sonuçlarını kontrol ettim; geçerli satırların aktarılmasını onaylıyorum.", key=f"{ui_prefix}_confirm")
    disabled = bool(duplicates or missing or dataset_type == "Bilinmeyen" or not confirmed or counts["Hazır"] + counts["Uyarılı"] == 0)
    if st.button("Doğrulanmış Verileri İçe Aktar", key=f"{ui_prefix}_import", type="primary", disabled=disabled):
        session = Session()
        try:
            batch_id, result = ImportExecutionService.execute(session, filename, file_bytes, dataset_type, validated, include_duplicates)
            st.session_state[f"{ui_prefix}_result"] = {"batch_id": batch_id, **result}
        except Exception as exc:
            st.error(f"Aktarım geri alındı; veritabanında kısmi kayıt bırakılmadı: {exc}")
        finally:
            session.close()

    result = st.session_state.get(f"{ui_prefix}_result")
    if result:
        st.success(f"Aktarım tamamlandı. Parti No: {result['batch_id']}")
        result_cols = st.columns(5)
        for col, key, label in zip(result_cols, ["imported", "skipped", "errors", "duplicates", "updated"], ["Eklenen", "Atlanan", "Hatalı", "Mükerrer", "Güncellenen"]):
            col.metric(label, result.get(key, 0))
        imported_preview = preview_df[preview_df["Aktarım Durumu"].isin(["Hazır", "Uyarılı"])]
        st.download_button("İçe Aktarılan Kayıtları İndir", _excel_bytes(imported_preview), "ice_aktarilan_kayitlar.xlsx", key=f"{ui_prefix}_imported_download")
        st.download_button("Aktarım Sonucunu İndir", json.dumps(result, ensure_ascii=False, indent=2), "aktarim_sonucu.json", "application/json", key=f"{ui_prefix}_result_download")


def _drive_filename(item):
    name = item.get("name", "Adsız dosya")
    return f"{Path(name).stem}.xlsx" if item.get("mimeType") == "application/vnd.google-apps.spreadsheet" else name


def _is_importable_drive_file(item):
    return item.get("mimeType") in ALLOWED_MIME_TYPES or Path(item.get("name", "")).suffix.lower() in SUPPORTED_EXTENSIONS


def render_drive_file_list(key_prefix="drive", show_import=True):
    initialize_drive_state()
    files = st.session_state.get("gdrive_files", [])
    if not files:
        empty_state("Dosya bulunamadı", "Bağlı klasörde dosya yok. Klasör paylaşımını ve klasör ID'sini kontrol edin.")
        return
    search = st.text_input("Dosya ara", key=f"{key_prefix}_file_search").strip().lower()
    filtered = [item for item in files if search in item.get("name", "").lower()]
    st.markdown("### Google Drive Dosyaları")
    st.caption(f"{len(filtered)} dosya gösteriliyor.")
    for item in filtered:
        file_id = item.get("id", "")
        modified = item.get("modifiedTime", "—")
        if modified != "—":
            try: modified = datetime.fromisoformat(modified.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
            except ValueError: pass
        info, preview, download, import_col = st.columns([6, 1, 1, 1])
        with info:
            st.markdown(f"**Dosya Adı:** {item.get('name', 'Adsız dosya')}")
            st.caption(f"Dosya Türü: {_format_drive_file_type(item.get('mimeType'))} • Son Değiştirilme: {modified} • Dosya Boyutu: {_human_readable_size(item.get('size'))}")
            st.code(f"Drive Dosya ID: {file_id}", language=None)
        with preview:
            if st.button("Önizle", key=f"{key_prefix}_preview_{file_id}", disabled=not _is_importable_drive_file(item)):
                st.session_state[f"{key_prefix}_selected_file_id"] = file_id
        with download:
            if st.button("İndir", key=f"{key_prefix}_prepare_download_{file_id}"):
                try:
                    buffer = download_drive_file(file_id, item.get("mimeType"))
                    st.session_state[f"{key_prefix}_download"] = {"id": file_id, "name": _drive_filename(item), "bytes": buffer.getvalue()}
                except Exception as exc: st.error(f"Dosya indirilemedi: {exc}")
        with import_col:
            if st.button("İçe Aktar", key=f"{key_prefix}_import_{file_id}", disabled=not show_import or not _is_importable_drive_file(item)):
                st.session_state[f"{key_prefix}_selected_file_id"] = file_id
    prepared = st.session_state.get(f"{key_prefix}_download")
    if prepared:
        st.download_button(f"{prepared['name']} dosyasını kaydet", prepared["bytes"], prepared["name"], key=f"{key_prefix}_download_ready_{prepared['id']}")
    selected_id = st.session_state.get(f"{key_prefix}_selected_file_id")
    selected = next((item for item in files if item.get("id") == selected_id), None)
    if selected:
        st.markdown("---")
        st.subheader(f"{selected['name']} — Önizleme ve İçe Aktarma")
        try:
            buffer = download_drive_file(selected["id"], selected["mimeType"])
            _render_import_workflow(buffer.getvalue(), _drive_filename(selected), f"{key_prefix}_{selected['id']}")
        except Exception as exc: st.error(f"Drive dosyası okunamadı veya işlenemedi: {exc}")


def render_drive_import():
    page_header("Excel Veri Aktarımı", "Excel/CSV dosyanızı güvenli biçimde analiz edin, doğrulayın ve doğru kayıtlara aktarın.")
    st.subheader("Bilgisayardan Yükle")
    uploaded = st.file_uploader("Dosya Seç", type=["xlsx", "xls", "csv"], key="local_excel_upload")
    if uploaded is not None:
        _render_import_workflow(uploaded.getvalue(), uploaded.name, "local")
    st.markdown("---")
    section_header("Google Drive’dan Al", "Aynı analiz, eşleştirme ve doğrulama hattı Drive dosyaları için de kullanılır.")
    initialize_drive_state()
    if not has_valid_drive_config():
        st.warning("Google Drive bağlantısı kurulmamış.")
        return
    if not st.session_state.gdrive_connected:
        st.info("Google Drive bilgileri hazır. Bağlantıyı Ayarlar sayfasından test edin.")
        return
    if st.button("Drive Dosyalarını Yenile", key="drive_refresh_files"):
        try:
            list_drive_files()
            st.success(f"{len(st.session_state.gdrive_files)} dosya bulundu ve aşağıda listelendi.")
        except Exception as exc:
            st.error(f"Drive dosyaları yenilenemedi: {exc}")
            return
    render_drive_file_list(key_prefix="drive_import", show_import=True)
