from apscheduler.schedulers.blocking import BlockingScheduler
from backend.workers.email_polling_worker import poll_email_accounts
from backend.workers.reminder_worker import generate_reminders
from backend.workers.current_account_worker import refresh_current_accounts

def build_scheduler():
    scheduler = BlockingScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(poll_email_accounts, "interval", minutes=10, id="email_polling", max_instances=1, coalesce=True)
    scheduler.add_job(generate_reminders, "cron", hour=7, minute=0, id="daily_reminders", max_instances=1, coalesce=True)
    scheduler.add_job(refresh_current_accounts, "cron", hour=6, minute=30, id="daily_current_accounts", max_instances=1, coalesce=True)
    return scheduler

if __name__ == "__main__": build_scheduler().start()
