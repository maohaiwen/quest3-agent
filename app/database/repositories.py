"""Data access layer repositories"""
from datetime import datetime
from typing import Optional, List
import json
import uuid

from app.database.connection import DatabaseConnection
from app.models.session import (SessionCreate, SessionUpdate, SessionResponse, SessionStatus, SessionCreateResponse)
from app.models.chat import MessageCreate, MessageResponse, MessageRole


class SessionRepository:
    """Session repository for database operations"""

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(self, session_data: SessionCreate) -> SessionCreateResponse:
        """Create a new session

        Args:
            session_data: Session creation data

        Returns:
            Created session response
        """
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        sql = """
        INSERT INTO sessions (id, user_id, title, agent_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        await self.db.execute(
            sql,
            (session_id, session_data.user_id, session_data.title, session_data.agent_id, SessionStatus.ACTIVE, now, now)
        )
        await self.db.commit()

        return SessionCreateResponse(session_id=session_id, created_at=datetime.fromisoformat(now))

    async def get(self, session_id: str) -> Optional[SessionResponse]:
        """Get session by ID

        Args:
            session_id: Session ID

        Returns:
            Session response or None
        """
        sql = "SELECT * FROM sessions WHERE id = ?"
        row = await self.db.fetch_one(sql, (session_id,))

        if row:
            # Count messages
            count_sql = "SELECT COUNT(*) as count FROM messages WHERE session_id = ?"
            count_row = await self.db.fetch_one(count_sql, (session_id,))
            message_count = count_row["count"] if count_row else 0

            return SessionResponse(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                agent_id=row.get("agent_id"),
                status=SessionStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                message_count=message_count
            )

        return None

    async def update(self, session_id: str, update_data: SessionUpdate) -> Optional[SessionResponse]:
        """Update session

        Args:
            session_id: Session ID
            update_data: Update data

        Returns:
            Updated session response or None
        """
        now = datetime.utcnow().isoformat()
        updates = []
        params = []

        if update_data.title is not None:
            updates.append("title = ?")
            params.append(update_data.title)

        if update_data.status is not None:
            updates.append("status = ?")
            params.append(update_data.status.value)

        if updates:
            params.extend([now, session_id])
            sql = f"UPDATE sessions SET {', '.join(updates)}, updated_at = ? WHERE id = ?"
            await self.db.execute(sql, tuple(params))
            await self.db.commit()

        return await self.get(session_id)

    async def delete(self, session_id: str) -> bool:
        """Delete session

        Args:
            session_id: Session ID

        Returns:
            True if deleted, False otherwise
        """
        sql = "DELETE FROM sessions WHERE id = ?"
        await self.db.execute(sql, (session_id,))
        await self.db.commit()

        return True

    async def get_history(self, session_id: str) -> List[MessageResponse]:
        """Get session message history

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        sql = "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC"
        rows = await self.db.fetch_all(sql, (session_id,))

        messages = []
        for row in rows:
            messages.append(MessageResponse(
                id=row["id"],
                session_id=row["session_id"],
                content=row["content"],
                role=MessageRole(row["role"]),
                created_at=datetime.fromisoformat(row["created_at"])
            ))

        return messages


class MessageRepository:
    """Message repository for database operations"""

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(self, message_data: MessageCreate) -> MessageResponse:
        """Create a new message

        Args:
            message_data: Message creation data

        Returns:
            Created message response
        """
        message_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        sql = """
        INSERT INTO messages (id, session_id, content, role, created_at)
        VALUES (?, ?, ?, ?, ?)
        """
        await self.db.execute(
            sql,
            (message_id, message_data.session_id, message_data.content, message_data.role.value, now)
        )
        await self.db.commit()

        return MessageResponse(
            id=message_id,
            session_id=message_data.session_id,
            content=message_data.content,
            role=message_data.role,
            created_at=datetime.fromisoformat(now)
        )

    async def get_by_session(self, session_id: str, limit: int = 10) -> List[MessageResponse]:
        """Get messages by session ID

        Args:
            session_id: Session ID
            limit: Maximum number of messages

        Returns:
            List of messages
        """
        sql = f"""
        SELECT * FROM messages
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """
        rows = await self.db.fetch_all(sql, (session_id, limit))

        messages = []
        for row in reversed(rows):  # Reverse to get chronological order
            messages.append(MessageResponse(
                id=row["id"],
                session_id=row["session_id"],
                content=row["content"],
                role=MessageRole(row["role"]),
                created_at=datetime.fromisoformat(row["created_at"])
            ))

        return messages


class MemoryRepository:
    """Memory repository for database operations"""

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(
        self,
        session_id: str,
        content: str,
        metadata: Optional[dict] = None
    ) -> str:
        """Create a new memory

        Args:
            session_id: Session ID
            content: Content to store
            metadata: Optional metadata

        Returns:
            Memory ID
        """
        memory_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        metadata_json = json.dumps(metadata) if metadata else None

        sql = """
        INSERT INTO memory (id, session_id, content, metadata, created_at)
        VALUES (?, ?, ?, ?, ?)
        """
        await self.db.execute(sql, (memory_id, session_id, content, metadata_json, now))
        await self.db.commit()

        return memory_id

    async def get_by_session(self, session_id: str) -> List[dict]:
        """Get memories by session ID

        Args:
            session_id: Session ID

        Returns:
            List of memories
        """
        sql = "SELECT * FROM memory WHERE session_id = ? ORDER BY created_at DESC"
        rows = await self.db.fetch_all(sql, (session_id,))

        memories = []
        for row in rows:
            memory = {
                "id": row["id"],
                "session_id": row["session_id"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
                "created_at": datetime.fromisoformat(row["created_at"])
            }
            memories.append(memory)

        return memories

    async def delete(self, memory_id: str) -> bool:
        """Delete memory

        Args:
            memory_id: Memory ID

        Returns:
            True if deleted
        """
        sql = "DELETE FROM memory WHERE id = ?"
        await self.db.execute(sql, (memory_id,))
        await self.db.commit()

        return True
