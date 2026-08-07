from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from database.db import database_url
from database.models import Base


config = context.config
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=database_url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None} if database_url.startswith("postgresql") else {},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
