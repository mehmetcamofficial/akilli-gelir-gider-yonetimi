from fastapi import FastAPI
from backend.api.email_webhooks import router as email_router
from backend.api.health import router as health_router
from backend.api.notifications import router as notification_router
from backend.api.whatsapp_webhooks import router as whatsapp_router

app = FastAPI(title="Tourism Accounting Communication Backend", version="1.0.0")
app.include_router(health_router); app.include_router(email_router); app.include_router(whatsapp_router); app.include_router(notification_router)
