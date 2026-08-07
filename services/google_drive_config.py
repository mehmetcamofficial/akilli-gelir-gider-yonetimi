import json
import re

import streamlit as st

from services.google_drive_service import (
    create_drive_service,
    delete_drive_file as _delete_drive_file,
    download_drive_file as _download_drive_file,
    get_drive_file_metadata as _get_drive_file_metadata,
    list_drive_excel_files,
    upload_drive_file as _upload_drive_file,
)


SERVICE_ACCOUNT_KEY = "gdrive_service_account"
FOLDER_ID_KEY = "gdrive_folder_id"
CONNECTED_KEY = "gdrive_connected"
FILES_KEY = "gdrive_files"
ERROR_KEY = "gdrive_connection_error"

REQUIRED_SERVICE_ACCOUNT_FIELDS = {
    "type",
    "project_id",
    "private_key",
    "client_email",
    "token_uri",
}


def _secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def _as_dict(value):
    if not value:
        return None
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError):
            return None
    try:
        return dict(value)
    except (TypeError, ValueError):
        return None


def normalize_folder_id(value):
    value = str(value or "").strip()
    if not value:
        return ""
    match = re.search(r"/folders/([^/?#]+)", value)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([^&#]+)", value)
    if match:
        return match.group(1)
    return value


def initialize_drive_state():
    st.session_state.setdefault(SERVICE_ACCOUNT_KEY, None)
    st.session_state.setdefault(FOLDER_ID_KEY, "")
    st.session_state.setdefault(CONNECTED_KEY, False)
    st.session_state.setdefault(FILES_KEY, [])
    st.session_state.setdefault(ERROR_KEY, None)


def get_service_account_info():
    initialize_drive_state()
    session_value = _as_dict(st.session_state.get(SERVICE_ACCOUNT_KEY))
    if session_value:
        return session_value

    drive_block = _secret("drive", {}) or {}
    drive_block = _as_dict(drive_block) or {}
    for value in (
        _secret("gcp_service_account"),
        _secret("drive_service_account_json"),
        drive_block.get("drive_service_account_json"),
        drive_block.get("service_account_json"),
    ):
        parsed = _as_dict(value)
        if parsed:
            return parsed
    return None


def get_drive_folder_id():
    initialize_drive_state()
    session_value = normalize_folder_id(st.session_state.get(FOLDER_ID_KEY))
    if session_value:
        return session_value

    drive_block = _as_dict(_secret("drive", {})) or {}
    return normalize_folder_id(
        _secret("drive_folder_id") or drive_block.get("drive_folder_id")
    )


def validate_service_account_info(service_account_info):
    parsed = _as_dict(service_account_info)
    if not parsed:
        raise ValueError("Geçerli bir Google servis hesabı JSON dosyası yükleyin.")
    missing = REQUIRED_SERVICE_ACCOUNT_FIELDS.difference(parsed)
    if missing:
        raise ValueError("Servis hesabı JSON dosyasında zorunlu alanlar eksik.")
    if parsed.get("type") != "service_account":
        raise ValueError("JSON dosyası bir Google servis hesabına ait değil.")
    return parsed


def has_valid_drive_config():
    try:
        validate_service_account_info(get_service_account_info())
    except ValueError:
        return False
    return bool(get_drive_folder_id())


def save_drive_config(service_account_info=None, folder_id=None):
    initialize_drive_state()
    changed = False
    if service_account_info is not None:
        parsed = validate_service_account_info(service_account_info)
        if parsed != st.session_state.get(SERVICE_ACCOUNT_KEY):
            st.session_state[SERVICE_ACCOUNT_KEY] = parsed
            changed = True
    if folder_id is not None:
        normalized = normalize_folder_id(folder_id)
        if normalized != st.session_state.get(FOLDER_ID_KEY):
            st.session_state[FOLDER_ID_KEY] = normalized
            changed = True
    if changed:
        st.session_state[CONNECTED_KEY] = False
        st.session_state[FILES_KEY] = []
        st.session_state[ERROR_KEY] = None


def clear_drive_config():
    initialize_drive_state()
    st.session_state[SERVICE_ACCOUNT_KEY] = None
    st.session_state[FOLDER_ID_KEY] = ""
    st.session_state[CONNECTED_KEY] = False
    st.session_state[FILES_KEY] = []
    st.session_state[ERROR_KEY] = None


def get_drive_service():
    account_info = validate_service_account_info(get_service_account_info())
    if not get_drive_folder_id():
        raise ValueError("Google Drive klasör ID girilmedi.")
    return create_drive_service(account_info)


def list_drive_files(service=None, folder_id=None):
    service = service or get_drive_service()
    folder_id = normalize_folder_id(folder_id) if folder_id else get_drive_folder_id()
    if not folder_id:
        raise ValueError("Google Drive klasör ID girilmedi.")
    files = list_drive_excel_files(folder_id, service)
    st.session_state[FILES_KEY] = files
    st.session_state[CONNECTED_KEY] = True
    st.session_state[ERROR_KEY] = None
    return files


def download_drive_file(file_id, mime_type, service=None):
    service = service or get_drive_service()
    return _download_drive_file(file_id, mime_type, service)


def upload_drive_file(filename, mime_type, content, service=None, folder_id=None):
    service = service or get_drive_service()
    folder_id = normalize_folder_id(folder_id) if folder_id else get_drive_folder_id()
    if not folder_id:
        raise ValueError("Drive klasör ID girilmedi.")
    return _upload_drive_file(folder_id, filename, mime_type, content, service)


def delete_drive_file(file_id, service=None):
    service = service or get_drive_service()
    return _delete_drive_file(file_id, service)


def get_drive_file_metadata(file_id, service=None):
    service = service or get_drive_service()
    return _get_drive_file_metadata(file_id, service)
