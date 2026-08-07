from datetime import datetime

from backend.services.communication_services import ScheduledJobService
from database.db import SessionLocal
from services.current_account_service import DailyCurrentAccountService


def refresh_current_accounts():
    session = SessionLocal()
    try:
        scheduled = datetime.utcnow().replace(hour=6, minute=30, second=0, microsecond=0)
        def refresh():
            result = DailyCurrentAccountService.refresh(session)
            return sum(result.values())
        run, duplicate = ScheduledJobService.run(session, "refresh_current_accounts", scheduled, refresh)
        return 0 if duplicate or run is None else run.processed_count
    finally:
        session.close()
