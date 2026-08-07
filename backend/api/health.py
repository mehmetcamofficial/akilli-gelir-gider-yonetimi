from fastapi import APIRouter
from database.db import database_health

router = APIRouter(tags=["health"])

@router.get("/health")
def health():
    result = database_health()
    return {"status": "ok" if result["ok"] else "error", "database_provider": result["provider"], "table_count": result["table_count"], "migration_revision": result["migration_revision"]}
