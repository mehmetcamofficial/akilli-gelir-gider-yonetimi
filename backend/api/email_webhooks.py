from fastapi import APIRouter, BackgroundTasks, HTTPException
from backend.workers.email_polling_worker import poll_email_accounts

router = APIRouter(prefix="/webhooks/email", tags=["email"])

@router.post("/sync")
def sync(background_tasks: BackgroundTasks):
    background_tasks.add_task(poll_email_accounts)
    return {"status": "accepted"}
