"""Settings and user database schema"""
from datetime import datetime


async def create_settings_tables(db):
    """Create settings and users tables

    Args:
        db: Database connection
    """

    # System settings table
    await db.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        default_value TEXT,
        description TEXT,
        group_name TEXT DEFAULT 'general',
        value_type TEXT DEFAULT 'string',
        editable INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    # Users table
    await db.execute("""
    CREATE TABLE IF NOT EXISTS app_users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        created_at TEXT,
        updated_at TEXT
    )
    """)

    await db.commit()
