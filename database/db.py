from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from .models import Base
import os
from .migrations import init_and_seed

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(Session, "after_commit")
def _invalidate_analytics_after_write(session):
    """Any successful create/edit/delete makes cached management figures stale."""
    if session.info.get("skip_analytics_cache_clear"):
        return
    try:
        from services.analytics_service import clear_analytics_cache
        clear_analytics_cache()
    except Exception:
        pass


def init_db():
    # create folders
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        init_and_seed()
    except OperationalError:
        pass


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
