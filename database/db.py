from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import streamlit as st
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def _database_url():
    try:
        value = str(st.secrets.get("DATABASE_URL", "sqlite:///database/app.db")).strip()
    except Exception:
        value = "sqlite:///database/app.db"
    parsed = make_url(value)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.drivername == "postgresql+psycopg" and "sslmode" not in parsed.query:
        parsed = parsed.update_query_dict({"sslmode": "require"})
    return parsed.render_as_string(hide_password=False)


database_url = _database_url()
_parsed_database_url = make_url(database_url)
IS_POSTGRESQL = _parsed_database_url.get_backend_name() == "postgresql"
IS_SUPABASE_POOLER = IS_POSTGRESQL and bool(_parsed_database_url.host and "pooler.supabase.com" in _parsed_database_url.host)


def validate_database_config(url=None):
    parsed_url = make_url(url) if url else _parsed_database_url
    is_postgresql = parsed_url.get_backend_name() == "postgresql"
    is_pooler = is_postgresql and bool(parsed_url.host and "pooler.supabase.com" in parsed_url.host)
    issues = []
    if is_postgresql:
        if not parsed_url.host: issues.append("PostgreSQL sunucusu eksik")
        if not parsed_url.database: issues.append("PostgreSQL veritabanı adı eksik")
        if parsed_url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}: issues.append("SSL zorunlu değil")
        if is_pooler and parsed_url.port not in {5432, 6543}: issues.append("Supabase pooler portu 5432 veya 6543 olmalı")
    return {
        "valid": not issues,
        "issues": issues,
        "provider": "PostgreSQL / Supabase" if is_postgresql else "SQLite (yerel geliştirme)",
        "pooler": "Supabase pooler" if is_pooler else ("Doğrudan PostgreSQL" if is_postgresql else "Yerel dosya"),
        "ssl": parsed_url.query.get("sslmode", "yerel"),
    }

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"prepare_threshold": None} if IS_POSTGRESQL else {},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

DATABASE_PROVIDER = "PostgreSQL / Supabase" if IS_POSTGRESQL else "SQLite (yerel geliştirme)"
_initialization_lock = Lock()
_initialized = False
_last_successful_query = None


@event.listens_for(Session, "after_commit")
def _invalidate_analytics_after_write(session):
    if session.info.get("skip_analytics_cache_clear"):
        return
    try:
        from services.cache_service import invalidate_application_cache
        invalidate_application_cache(clear_session=False)
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
        configuration = validate_database_config()
        if not configuration["valid"]:
            raise RuntimeError("Veritabanı ayarı geçersiz: " + "; ".join(configuration["issues"]))
        from alembic import command
        from alembic.config import Config
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        if len(inspect(engine).get_table_names()) < len(Base.metadata.tables):
            raise RuntimeError("Veritabanı şeması eksik; Alembic tüm tabloları oluşturamadı.")
        _initialized = True


def database_health():
    """Return safe connection metadata without exposing credentials or host details."""
    global _last_successful_query
    try:
        with engine.connect() as connection:
            connection.execute(select(1)).scalar_one()
            table_names = inspect(connection).get_table_names()
            table_count = len([name for name in table_names if name != "alembic_version"])
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none() if "alembic_version" in table_names else None
        _last_successful_query = datetime.now(timezone.utc)
        configuration = validate_database_config()
        return {
            "ok": True,
            "message": "PostgreSQL bağlantısı başarılı" if engine.dialect.name == "postgresql" else "SQLite yerel bağlantısı başarılı",
            "provider": DATABASE_PROVIDER,
            "table_count": table_count,
            "expected_table_count": len(Base.metadata.tables),
            "migration_revision": revision,
            "pooler": configuration["pooler"],
            "ssl": configuration["ssl"],
            "last_successful_query": _last_successful_query,
        }
    except SQLAlchemyError as exc:
        return {
            "ok": False,
            "message": "Veritabanı bağlantısı başarısız",
            "provider": DATABASE_PROVIDER,
            "table_count": None,
            "expected_table_count": len(Base.metadata.tables),
            "migration_revision": None,
            "pooler": validate_database_config()["pooler"],
            "ssl": validate_database_config()["ssl"],
            "last_successful_query": _last_successful_query,
            "error_type": type(exc).__name__,
        }


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
