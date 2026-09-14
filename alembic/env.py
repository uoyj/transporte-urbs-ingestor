"""Alembic environment configuration.

Uses environment variables for DB connection; falls back to defaults from
docker-compose.yml when running inside the container network.
"""
from logging.config import fileConfig
from os import environ
from sqlalchemy import engine_from_config, pool
from alembic import context

from src.models import Base  # import models for autogenerate

# Interpret the config file for Python logging.
config = context.config

# Set URL from environment vars if provided, otherwise use alembic.ini value.
db_user = environ.get("POSTGRES_USER", "urbs_user")
db_pass = environ.get("POSTGRES_PASSWORD", "")
db_host = environ.get("POSTGRES_HOST", "192.168.2.200")
db_name = environ.get("POSTGRES_DB", "urbs_db")
db_port = environ.get("POSTGRES_PORT", "5432")

config.set_main_option(
    "sqlalchemy.url",
    f"postgresql+psycopg2://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}",
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()