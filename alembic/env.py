"""Alembic env.py — configured for Quest3 Agent

Reads DATABASE_URL from app.config.settings and uses the application's
SQLAlchemy metadata for autogenerate support.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Read database URL from app config (supports .env and DB override)
# ---------------------------------------------------------------------------
try:
    from app.config import settings

    db_url = settings.DATABASE_URL
    # Alembic expects a URL without the +aiosqlite dialect modifier
    # for synchronous engine creation
    sync_url = db_url.replace("+aiosqlite", "")
    config.set_main_option("sqlalchemy.url", sync_url)
except Exception:
    pass  # Fallback to alembic.ini default


# ---------------------------------------------------------------------------
# Target metadata for autogenerate
# ---------------------------------------------------------------------------
# Currently we use raw SQL schema (no SQLAlchemy ORM models).
# Set target_metadata = None so autogenerate won't try to diff against
# non-existent models. When ORM models are added, import their Base here.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() emit the given string to script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
