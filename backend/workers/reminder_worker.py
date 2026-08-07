from datetime import datetime
from database.db import SessionLocal
from backend.services.communication_services import ReminderService, ScheduledJobService

def generate_reminders():
    session = SessionLocal()
    try:
        scheduled = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        run, duplicate = ScheduledJobService.run(session, "generate_reminders", scheduled, lambda: ReminderService.generate(session))
        return 0 if duplicate else run.processed_count
    finally: session.close()
