import json
import os
from database.db import SessionLocal
from database.models import EmailAccount
from backend.services.communication_services import EmailIngestionService, GmailProvider

def _gmail_provider():
    raw = os.getenv("GMAIL_OAUTH_USER_CREDENTIALS")
    if not raw: raise RuntimeError("Gmail OAuth deployment secret is not configured")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    credentials = Credentials.from_authorized_user_info(json.loads(raw), ["https://www.googleapis.com/auth/gmail.modify"])
    return GmailProvider(build("gmail", "v1", credentials=credentials, cache_discovery=False))

def poll_email_accounts():
    session = SessionLocal(); processed = 0
    try:
        provider = _gmail_provider()
        for account in session.query(EmailAccount).filter_by(provider="gmail", is_active=True).all(): EmailIngestionService(provider).sync(session, account); processed += 1
        return processed
    finally: session.close()
