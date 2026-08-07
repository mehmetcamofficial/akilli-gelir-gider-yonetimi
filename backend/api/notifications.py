from datetime import datetime
from fastapi import APIRouter, HTTPException
from database.db import SessionLocal
from database.models import Notification, NotificationEvent

router = APIRouter(prefix="/notifications", tags=["notifications"])

@router.get("")
def list_notifications(unread: bool = False):
    session = SessionLocal()
    try:
        query = session.query(Notification)
        if unread: query = query.filter(Notification.is_read.is_(False), Notification.dismissed_at.is_(None))
        return [{"id": x.id, "type": x.notification_type, "level": x.level, "text": x.rendered_text, "status": x.status, "due_date": x.due_date} for x in query.order_by(Notification.created_at.desc()).limit(200)]
    finally: session.close()

@router.post("/{notification_id}/read")
def mark_read(notification_id: int):
    session = SessionLocal()
    try:
        item = session.get(Notification, notification_id)
        if not item: raise HTTPException(404, "Bildirim bulunamadı")
        item.is_read = True; session.add(NotificationEvent(notification_id=item.id, event_type="read")); session.commit(); return {"status": "ok"}
    finally: session.close()
