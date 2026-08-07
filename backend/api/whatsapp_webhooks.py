import os
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request
from database.db import SessionLocal
from database.models import WhatsAppAccount
from backend.services.communication_services import WhatsAppIngestionService

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])

@router.get("")
def verify(hub_mode: str = Query(alias="hub.mode"), hub_challenge: str = Query(alias="hub.challenge"), hub_verify_token: str = Query(alias="hub.verify_token")):
    if hub_mode != "subscribe" or not os.getenv("WHATSAPP_VERIFY_TOKEN") or hub_verify_token != os.getenv("WHATSAPP_VERIFY_TOKEN"): raise HTTPException(403, "Webhook doğrulaması başarısız")
    return int(hub_challenge)

def _process(payload):
    session = SessionLocal()
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {}); phone_id = value.get("metadata", {}).get("phone_number_id")
                account = session.query(WhatsAppAccount).filter_by(phone_number_id=phone_id).first()
                if not account: continue
                contacts = {item.get("wa_id"): item.get("profile", {}).get("name") for item in value.get("contacts", [])}
                for message in value.get("messages", []):
                    media = message.get(message.get("type"), {}) if message.get("type") in {"image", "document", "audio"} else {}
                    message_payload = {"id": message.get("id"), "from": message.get("from"), "type": message.get("type"), "text": message.get("text", {}).get("body", "") or media.get("caption", ""), "media_id": media.get("id"), "mime_type": media.get("mime_type"), "profile_name": contacts.get(message.get("from")), "timestamp": message.get("timestamp")}
                    WhatsAppIngestionService.ingest(session, account, message.get("id"), message_payload)
    finally: session.close()

@router.post("")
async def receive(request: Request, background_tasks: BackgroundTasks, x_hub_signature_256: str | None = Header(default=None)):
    body = await request.body()
    if not WhatsAppIngestionService.verify_signature(body, x_hub_signature_256): raise HTTPException(401, "İmza doğrulanamadı")
    payload = await request.json(); background_tasks.add_task(_process, payload)
    return {"status": "accepted"}
