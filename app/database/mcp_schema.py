"""MCP server database schema"""
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text
)
from sqlalchemy.ext.asyncio import AsyncSession


async def create_mcp_tables(db):
    """Create MCP related tables

    Args:
        db: Database connection
    """
    # MCP servers table
    await db.execute("""
    CREATE TABLE IF NOT EXISTS mcp_servers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        description TEXT,
        priority INTEGER DEFAULT 0,
        enabled BOOLEAN DEFAULT 1,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_connected TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        headers TEXT DEFAULT '{}',
        server_type TEXT DEFAULT 'standard'
    )
    """)

    # Add missing columns for backward compatibility
    try:
        await db.execute("""
        ALTER TABLE mcp_servers ADD COLUMN headers TEXT DEFAULT '{}'
        """)
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise

    try:
        await db.execute("""
        ALTER TABLE mcp_servers ADD COLUMN server_type TEXT DEFAULT 'standard'
        """)
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise

    await db.commit()

    # Agents table
    await db.execute("""
    CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        type TEXT DEFAULT 'custom',
        system_prompt TEXT,
        model TEXT,
        temperature REAL,
        max_tokens INTEGER,
        execution_mode TEXT DEFAULT 'plan',
        enabled INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        usage_count INTEGER DEFAULT 0
    )
    """)

    # Add missing columns for backward compatibility
    try:
        await db.execute("""
        ALTER TABLE agents ADD COLUMN type TEXT DEFAULT 'custom'
        """)
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise

    try:
        await db.execute("""
        ALTER TABLE agents ADD COLUMN execution_mode TEXT DEFAULT 'plan'
        """)
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise

    try:
        await db.execute("""
        ALTER TABLE agents ADD COLUMN thinking_effort TEXT DEFAULT 'medium'
        """)
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise

    try:
        await db.execute("""
        ALTER TABLE agents ADD COLUMN max_react_steps INTEGER DEFAULT 15
        """)
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise

    # Agent MCP servers mapping
    await db.execute("""
    CREATE TABLE IF NOT EXISTS agent_mcp_servers (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        server_id TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
        FOREIGN KEY (server_id) REFERENCES mcp_servers(id) ON DELETE CASCADE
    )
    """)

    # Agent tools configuration
    await db.execute("""
    CREATE TABLE IF NOT EXISTS agent_tools (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        permission TEXT DEFAULT 'optional',
        description TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
    )
    """)

    # Add agent_id to sessions table
    try:
        await db.execute("""
        ALTER TABLE sessions ADD COLUMN agent_id TEXT
        """)
        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions(agent_id)
        """)
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise

    await db.commit()


async def migrate_mcp_servers_from_settings(db: AsyncSession):
    """Migrate MCP servers from settings (if any)

    Args:
        db: Database session
    """
    from app.config import settings

    mcp_server_url = getattr(settings, 'MCP_SERVER_URL', None)
    if mcp_server_url:
        # Check if server already exists
        existing = await db.execute(
            "SELECT id FROM mcp_servers WHERE url = ?",
            (mcp_server_url,)
        ).fetchone()

        if not existing:
            import uuid
            server_id = str(uuid.uuid4())

            await db.execute("""
            INSERT INTO mcp_servers (id, name, url, description, priority, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (server_id, "Default MCP Server", mcp_server_url, "Migrated from settings", 1, 1))

            await db.commit()

