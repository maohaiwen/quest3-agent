"""Database connection management — with write-lock and transaction support

SQLite only allows one writer at a time. This module:
- Uses a single connection with WAL mode for concurrent reads
- Serializes writes through an asyncio.Lock
- Provides a transaction() context manager for atomic operations
- Maintains full backward compatibility with the previous API
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Async SQLite database connection manager with write serialization.

    SQLite WAL mode allows concurrent reads while one write is in progress.
    We protect writes with an asyncio.Lock so coroutines don't step on
    each other's transactions.
    """

    def __init__(self, database_url: str):
        """Initialize database connection manager.

        Args:
            database_url: Database URL in format sqlite+aiosqlite:///path/to/db
        """
        self.database_url = database_url
        self.db_path: Optional[Path] = None
        self.connection: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()
        # Flag: when inside a transaction() context, execute/commit/rollback
        # skip acquiring _write_lock because the transaction already holds it.
        self._in_transaction = False

    def _parse_url(self) -> Path:
        """Parse database URL and return path."""
        db_path_str = self.database_url.replace("sqlite+aiosqlite:///", "")
        if db_path_str.startswith("./"):
            db_path_str = db_path_str[2:]
        return Path(db_path_str)

    async def connect(self) -> aiosqlite.Connection:
        """Connect to database.

        Returns:
            Database connection
        """
        if self.connection is None:
            self.db_path = self._parse_url()

            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self.connection = await aiosqlite.connect(self.db_path)

            # Enable foreign keys
            await self.connection.execute("PRAGMA foreign_keys = ON")

            # Configure WAL mode for better concurrency
            await self.connection.execute("PRAGMA journal_mode = WAL")

            # Use Row factory for dict-like access
            self.connection.row_factory = aiosqlite.Row

        return self.connection

    async def disconnect(self) -> None:
        """Close database connection"""
        if self.connection:
            await self.connection.close()
            self.connection = None

    # -----------------------------------------------------------------------
    # Write operations (serialized through _write_lock)
    # -----------------------------------------------------------------------

    async def execute(self, sql: str, params: Optional[tuple] = None) -> aiosqlite.Cursor:
        """Execute SQL query (write-safe via lock).

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            Cursor
        """
        conn = await self.connect()
        if self._in_transaction:
            # Already inside transaction() which holds the write lock
            if params:
                return await conn.execute(sql, params)
            return await conn.execute(sql)
        async with self._write_lock:
            if params:
                return await conn.execute(sql, params)
            return await conn.execute(sql)

    async def execute_many(
        self, sql: str, params: list[tuple]
    ) -> aiosqlite.Cursor:
        """Execute SQL query multiple times."""
        conn = await self.connect()
        if self._in_transaction:
            return await conn.executemany(sql, params)
        async with self._write_lock:
            return await conn.executemany(sql, params)

    async def commit(self) -> None:
        """Commit transaction."""
        if self.connection:
            if self._in_transaction:
                # Transaction context manages commit
                return
            async with self._write_lock:
                await self.connection.commit()

    async def rollback(self) -> None:
        """Rollback transaction."""
        if self.connection:
            if self._in_transaction:
                return
            async with self._write_lock:
                await self.connection.rollback()

    # -----------------------------------------------------------------------
    # Read operations (no lock needed — WAL mode allows concurrent reads)
    # -----------------------------------------------------------------------

    async def fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[dict]:
        """Fetch one row.

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            Row as dictionary or None
        """
        conn = await self.connect()
        if params:
            cursor = await conn.execute(sql, params)
        else:
            cursor = await conn.execute(sql)
        row = await cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))

        return None

    async def fetch_all(self, sql: str, params: Optional[tuple] = None) -> list[dict]:
        """Fetch all rows.

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            List of rows as dictionaries
        """
        conn = await self.connect()
        if params:
            cursor = await conn.execute(sql, params)
        else:
            cursor = await conn.execute(sql)
        rows = await cursor.fetchall()

        if rows:
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

        return []

    # -----------------------------------------------------------------------
    # Transaction context manager
    # -----------------------------------------------------------------------

    @asynccontextmanager
    async def transaction(self):
        """Async context manager for database transactions.

        Automatically commits on success, rolls back on exception.
        Holds the write lock for the entire transaction scope.

        Usage:
            async with db.transaction():
                await db.execute("INSERT ...", (...))
                await db.execute("UPDATE ...", (...))
                # auto-commit on exit, auto-rollback on exception
        """
        conn = await self.connect()
        async with self._write_lock:
            self._in_transaction = True
            try:
                yield
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
            finally:
                self._in_transaction = False

    # -----------------------------------------------------------------------
    # Schema initialization (kept for backward compat, will migrate to Alembic)
    # -----------------------------------------------------------------------

    async def initialize_schema(self) -> None:
        """Initialize database schema."""
        await self._create_sessions_table()
        await self._create_messages_table()
        await self._create_memory_table()
        await self._create_skills_table()
        await self._create_agent_skills_table()
        await self._create_agents_table()
        await self._create_agent_memories_table()
        await self._create_collaborations_table()
        await self._create_collaboration_agents_table()
        await self._create_collaboration_tasks_table()
        await self._create_collaboration_artifacts_table()
        await self._create_task_events_table()
        await self._create_settings_table()
        await self._create_users_table()

    async def _create_sessions_table(self) -> None:
        """Create sessions table"""
        sql = """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            title TEXT,
            agent_id TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
        await self.execute(sql)
        await self.commit()
        try:
            await self.execute("ALTER TABLE sessions ADD COLUMN agent_id TEXT")
            await self.commit()
        except Exception:
            pass

    async def _create_messages_table(self) -> None:
        """Create messages table"""
        sql = """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            content TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id)"
        )
        await self.commit()

    async def _create_memory_table(self) -> None:
        """Create memory table"""
        sql = """
        CREATE TABLE IF NOT EXISTS memory (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_session_id ON memory (session_id)"
        )
        await self.commit()

    async def _create_skills_table(self) -> None:
        """Create skills table"""
        sql = """
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            version TEXT DEFAULT '1.0.0',
            author TEXT,
            tags TEXT,
            source TEXT DEFAULT 'user',
            requirements TEXT DEFAULT '[]',
            tools TEXT,
            config_schema TEXT,
            entrypoint TEXT,
            skill_content TEXT NOT NULL,
            dir_path TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
        await self.execute(sql)
        try:
            await self.execute("ALTER TABLE skills ADD COLUMN requirements TEXT DEFAULT '[]'")
            await self.commit()
        except Exception:
            pass
        await self.execute("CREATE INDEX IF NOT EXISTS idx_skills_name ON skills (name)")
        await self.commit()

    async def _create_agent_skills_table(self) -> None:
        """Create agent-skills association table"""
        sql = """
        CREATE TABLE IF NOT EXISTS agent_skills (
            agent_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (agent_id, skill_id)
        )
        """
        await self.execute(sql)
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_skills_agent_id ON agent_skills (agent_id)"
        )
        await self.commit()

    async def _create_agents_table(self) -> None:
        """Create agents table if not exists"""
        sql = """
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            type TEXT DEFAULT 'custom',
            execution_mode TEXT DEFAULT 'plan',
            system_prompt TEXT,
            model TEXT,
            temperature REAL,
            max_tokens INTEGER,
            mcp_servers TEXT,
            tools TEXT,
            enabled INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 0,
            thinking_effort TEXT DEFAULT 'medium',
            max_react_steps INTEGER DEFAULT 15,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            usage_count INTEGER DEFAULT 0
        )
        """
        try:
            await self.execute(sql)
            await self.commit()
        except Exception:
            pass
        try:
            await self.execute("ALTER TABLE agents ADD COLUMN enable_long_term_memory INTEGER DEFAULT 0")
            await self.commit()
        except Exception:
            pass

    async def _create_agent_memories_table(self) -> None:
        """Create agent_memories table for long-term agent-level memory"""
        sql = """
        CREATE TABLE IF NOT EXISTS agent_memories (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            session_id TEXT,
            content TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            importance REAL DEFAULT 0.5,
            access_count INTEGER DEFAULT 0,
            source TEXT DEFAULT 'auto',
            metadata TEXT,
            created_at TEXT NOT NULL,
            last_accessed_at TEXT,
            FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_memories_agent_id ON agent_memories(agent_id)"
        )
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_memories_type ON agent_memories(agent_id, memory_type)"
        )
        await self.commit()

    async def _create_collaborations_table(self) -> None:
        """Create collaborations table"""
        sql = """
        CREATE TABLE IF NOT EXISTS collaborations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            mode TEXT DEFAULT 'supervisor',
            config_json TEXT DEFAULT '{}',
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            usage_count INTEGER DEFAULT 0
        )
        """
        await self.execute(sql)
        await self.commit()

    async def _create_collaboration_agents_table(self) -> None:
        """Create collaboration_agents table"""
        sql = """
        CREATE TABLE IF NOT EXISTS collaboration_agents (
            id TEXT PRIMARY KEY,
            collaboration_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            role TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            is_human INTEGER DEFAULT 0,
            config_json TEXT DEFAULT '{}',
            FOREIGN KEY (collaboration_id) REFERENCES collaborations(id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_collaboration_agents_collab_id ON collaboration_agents (collaboration_id)"
        )
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_collaboration_agents_agent_id ON collaboration_agents (agent_id)"
        )
        await self.commit()

    async def _create_collaboration_tasks_table(self) -> None:
        """Create collaboration_tasks table"""
        sql = """
        CREATE TABLE IF NOT EXISTS collaboration_tasks (
            id TEXT PRIMARY KEY,
            collaboration_id TEXT NOT NULL,
            task_id TEXT NOT NULL UNIQUE,
            input TEXT,
            output TEXT,
            status TEXT DEFAULT 'pending',
            messages_json TEXT,
            events_json TEXT,
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (collaboration_id) REFERENCES collaborations(id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)
        try:
            await self.execute("ALTER TABLE collaboration_tasks ADD COLUMN events_json TEXT")
        except Exception:
            pass
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_collaboration_tasks_collab_id ON collaboration_tasks (collaboration_id)"
        )
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_collaboration_tasks_task_id ON collaboration_tasks (task_id)"
        )
        await self.commit()

    async def _create_collaboration_artifacts_table(self) -> None:
        """Create collaboration_artifacts table"""
        sql = """
        CREATE TABLE IF NOT EXISTS collaboration_artifacts (
            id TEXT PRIMARY KEY,
            collaboration_id TEXT NOT NULL,
            task_id TEXT,
            round INTEGER DEFAULT 1,
            producer_agent_id TEXT,
            producer_role TEXT,
            name TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (collaboration_id) REFERENCES collaborations(id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_collab_id ON collaboration_artifacts (collaboration_id)"
        )
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_task_id ON collaboration_artifacts (task_id)"
        )
        await self.commit()

    async def _create_task_events_table(self) -> None:
        """Create task_events table for per-row event storage"""
        sql = """
        CREATE TABLE IF NOT EXISTS task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_json TEXT NOT NULL,
            created_at TEXT,
            FOREIGN KEY (task_id) REFERENCES collaboration_tasks(task_id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events (task_id)"
        )
        await self.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_events_task_type ON task_events (task_id, event_type)"
        )
        await self.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_events_task_seq ON task_events (task_id, seq)"
        )
        await self.commit()

    async def _create_settings_table(self) -> None:
        """Create app_settings table"""
        sql = """
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
        """
        await self.execute(sql)
        await self.commit()

    async def _create_users_table(self) -> None:
        """Create app_users table"""
        sql = """
        CREATE TABLE IF NOT EXISTS app_users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT,
            updated_at TEXT
        )
        """
        await self.execute(sql)
        await self.commit()
