"""Database connection management"""
import aiosqlite
from pathlib import Path
from typing import Optional


class DatabaseConnection:
    """Async SQLite database connection manager"""

    def __init__(self, database_url: str):
        """Initialize database connection

        Args:
            database_url: Database URL in format sqlite+aiosqlite:///path/to/db
        """
        self.database_url = database_url
        self.db_path: Optional[Path] = None
        self.connection: Optional[aiosqlite.Connection] = None

    def _parse_url(self) -> Path:
        """Parse database URL and return path

        Returns:
            Database file path
        """
        # Remove sqlite+aiosqlite:/// prefix
        db_path_str = self.database_url.replace("sqlite+aiosqlite:///", "")

        # Handle relative paths
        if db_path_str.startswith("./"):
            db_path_str = db_path_str[2:]

        return Path(db_path_str)

    async def connect(self) -> aiosqlite.Connection:
        """Connect to database

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

        return self.connection

    async def disconnect(self) -> None:
        """Close database connection"""
        if self.connection:
            await self.connection.close()
            self.connection = None

    async def execute(self, sql: str, params: Optional[tuple] = None) -> aiosqlite.Cursor:
        """Execute SQL query

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            Cursor
        """
        conn = await self.connect()
        if params:
            return await conn.execute(sql, params)
        return await conn.execute(sql)

    async def execute_many(
        self, sql: str, params: list[tuple]
    ) -> aiosqlite.Cursor:
        """Execute SQL query multiple times

        Args:
            sql: SQL query
            params: List of parameter tuples

        Returns:
            Cursor
        """
        conn = await self.connect()
        return await conn.executemany(sql, params)

    async def fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[dict]:
        """Fetch one row

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            Row as dictionary or None
        """
        cursor = await self.execute(sql, params)
        row = await cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))

        return None

    async def fetch_all(self, sql: str, params: Optional[tuple] = None) -> list[dict]:
        """Fetch all rows

        Args:
            sql: SQL query
            params: Query parameters

        Returns:
            List of rows as dictionaries
        """
        cursor = await self.execute(sql, params)
        rows = await cursor.fetchall()

        if rows:
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

        return []

    async def commit(self) -> None:
        """Commit transaction"""
        if self.connection:
            await self.connection.commit()

    async def rollback(self) -> None:
        """Rollback transaction"""
        if self.connection:
            await self.connection.rollback()

    async def initialize_schema(self) -> None:
        """Initialize database schema"""
        await self._create_sessions_table()
        await self._create_messages_table()
        await self._create_memory_table()
        await self._create_skills_table()
        await self._create_agent_skills_table()
        await self._create_agents_table()
        await self._create_collaborations_table()
        await self._create_collaboration_agents_table()
        await self._create_collaboration_tasks_table()

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

        # Add agent_id column if it doesn't exist (for existing databases)
        try:
            await self.execute("ALTER TABLE sessions ADD COLUMN agent_id TEXT")
            await self.commit()
        except Exception:
            pass  # Column already exists

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

        # Create index for faster queries
        sql = """
        CREATE INDEX IF NOT EXISTS idx_messages_session_id
        ON messages (session_id)
        """
        await self.execute(sql)
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

        # Create index for faster queries
        sql = """
        CREATE INDEX IF NOT EXISTS idx_memory_session_id
        ON memory (session_id)
        """
        await self.execute(sql)
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

        # Add requirements column if it doesn't exist
        try:
            await self.execute("ALTER TABLE skills ADD COLUMN requirements TEXT DEFAULT '[]'")
            await self.commit()
        except Exception:
            pass  # Column already exists

        sql = """
        CREATE INDEX IF NOT EXISTS idx_skills_name
        ON skills (name)
        """
        await self.execute(sql)
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

        sql = """
        CREATE INDEX IF NOT EXISTS idx_agent_skills_agent_id
        ON agent_skills (agent_id)
        """
        await self.execute(sql)
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
            pass  # Table might already exist

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
            config_json TEXT DEFAULT '{}',
            FOREIGN KEY (collaboration_id) REFERENCES collaborations(id) ON DELETE CASCADE,
            FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)

        # Create indexes
        sql = """
        CREATE INDEX IF NOT EXISTS idx_collaboration_agents_collab_id
        ON collaboration_agents (collaboration_id)
        """
        await self.execute(sql)

        sql = """
        CREATE INDEX IF NOT EXISTS idx_collaboration_agents_agent_id
        ON collaboration_agents (agent_id)
        """
        await self.execute(sql)
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
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (collaboration_id) REFERENCES collaborations(id) ON DELETE CASCADE
        )
        """
        await self.execute(sql)

        # Create indexes
        sql = """
        CREATE INDEX IF NOT EXISTS idx_collaboration_tasks_collab_id
        ON collaboration_tasks (collaboration_id)
        """
        await self.execute(sql)

        sql = """
        CREATE INDEX IF NOT EXISTS idx_collaboration_tasks_task_id
        ON collaboration_tasks (task_id)
        """
        await self.execute(sql)
        await self.commit()
