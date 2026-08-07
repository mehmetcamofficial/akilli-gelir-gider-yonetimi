import streamlit as st


PERSISTENT_SESSION_KEYS = {
    "active_page", "gdrive_service_account", "gdrive_folder_id", "gdrive_connected",
    "gdrive_files", "gdrive_connection_error",
}
DATA_STATE_PREFIXES = (
    "dashboard_", "analytics_", "invoice_", "booking_", "tour_", "document_",
    "archive_", "reconciliation_", "rec_", "local_", "drive_import_", "control_",
)


def _has_streamlit_context():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx(suppress_warning=True) is not None
    except Exception:
        return False


def invalidate_application_cache(clear_session=False):
    """Invalidate cached database-derived values after a successful write."""
    if not _has_streamlit_context():
        return
    st.cache_data.clear()
    if clear_session:
        for key in list(st.session_state):
            if key not in PERSISTENT_SESSION_KEYS and key.startswith(DATA_STATE_PREFIXES):
                st.session_state.pop(key, None)


def reset_demo_runtime_state():
    """Clear every data-dependent widget/result while retaining Drive configuration."""
    if not _has_streamlit_context():
        return
    st.cache_data.clear()
    st.cache_resource.clear()
    for key in list(st.session_state):
        if key not in PERSISTENT_SESSION_KEYS:
            st.session_state.pop(key, None)
