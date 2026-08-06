from datetime import datetime, timezone
from threading import Lock

import streamlit as st
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def _database_url():
    try:
        value = str(st.secrets.get("DATABASE_URL", "sqlite:///database/app.db"))
    except Exception:
        value = "sqlite:///database/app.db"
    # SQLAlchemy's explicit psycopg dialect guarantees psycopg v3, not psycopg2.
    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+psycopg://", 1)
    elif value.startswith("postgres://"):
        value = value.replace("postgres://", "postgresql+psycopg://", 1)
    return value


database_url = _database_url()

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

DATABASE_PROVIDER = "PostgreSQL / Supabase" if engine.dialect.name == "postgresql" else "SQLite (yerel geliştirme)"
_initialization_lock = Lock()
_initialized = False
_last_successful_query = None


@event.listens_for(Session, "after_commit")
def _invalidate_analytics_after_write(session):
    if session.info.get("skip_analytics_cache_clear"):
        return
    try:
        from services.analytics_service import clear_analytics_cache
        clear_analytics_cache()
    except Exception:
        pass


def init_db():
    """Create missing tables once per process; never drop or overwrite tables."""
    global _initialized
    if _initialized:
        return
    with _initialization_lock:
        if _initialized:
            return
        if engine.dialect.name == "postgresql":
            # Prevent two fresh Streamlit workers from racing on first deployment.
            with engine.begin() as connection:
                connection.execute(text("SELECT pg_advisory_xact_lock(726384921)"))
                Base.metadata.create_all(bind=connection, checkfirst=True)
        else:
            Base.metadata.create_all(bind=engine, checkfirst=True)
            # Legacy additive migrations are only needed by old local SQLite files.
            from .migrations import migrate_schema
            migrate_schema()
        _initialized = True


def database_health():
    """Return safe connection metadata without exposing credentials or host details."""
    global _last_successful_query
    try:
        with engine.connect() as connection:
            connection.execute(select(1)).scalar_one()
            table_count = len(inspect(connection).get_table_names())
        _last_successful_query = datetime.now(timezone.utc)
        return {
            "ok": True,
            "message": "PostgreSQL bağlantısı başarılı" if engine.dialect.name == "postgresql" else "SQLite yerel bağlantısı başarılı",
            "provider": DATABASE_PROVIDER,
            "table_count": table_count,
            "last_successful_query": _last_successful_query,
        }
    except SQLAlchemyError as exc:
        return {
            "ok": False,
            "message": "Veritabanı bağlantısı başarısız",
            "provider": DATABASE_PROVIDER,
            "table_count": None,
            "last_successful_query": _last_successful_query,
            "error_type": type(exc).__name__,
        }


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
