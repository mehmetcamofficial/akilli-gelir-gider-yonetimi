import json
from io import BytesIO

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def create_drive_service(service_account_info):
    if not service_account_info:
        raise ValueError("Google Drive servis hesabı JSON bilgisi sağlanmadı.")

    if isinstance(service_account_info, str):
        service_account_info = json.loads(service_account_info)

    credentials = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def list_drive_excel_files(folder_id, service):
    query = (
        f"'{folder_id}' in parents and (mimeType = 'application/vnd.google-apps.spreadsheet'"
        " or mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'"
        " or mimeType = 'application/vnd.ms-excel')"
    )
    results = []
    page_token = None

    while True:
        response = service.files().list(
            q=query,
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
            pageToken=page_token,
            pageSize=200,
        ).execute()
        files = response.get("files", [])
        for f in files:
            results.append(f)
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return results


def download_drive_file(file_id, file_mime_type, service):
    buffer = BytesIO()
    if file_mime_type == "application/vnd.google-apps.spreadsheet":
        request = service.files().export_media(
            fileId=file_id,
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        request = service.files().get_media(fileId=file_id)

    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

    buffer.seek(0)
    return buffer
