"""Data access layer repositories"""
from datetime import datetime
from app.utils.timezone import beijing_now
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
        now = beijing_now().isoformat()

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
        now = beijing_now().isoformat()
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

    async def count_messages(self, session_id: str) -> int:
        """Count total messages in a session

        Args:
            session_id: Session ID

        Returns:
            Message count
        """
        sql = "SELECT COUNT(*) as count FROM messages WHERE session_id = ?"
        row = await self.db.fetch_one(sql, (session_id,))
        return row["count"] if row else 0

    async def get_history(self, session_id: str, limit: int = None) -> List[MessageResponse]:
        """Get session message history

        Args:
            session_id: Session ID
            limit: Maximum number of recent messages to return (None = all)

        Returns:
            List of messages
        """
        if limit:
            sql = "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?"
            rows = await self.db.fetch_all(sql, (session_id, limit))
            rows = list(reversed(rows))  # Reverse to chronological order
        else:
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

    async def get_older_messages(self, session_id: str, before_count: int, limit: int) -> List[MessageResponse]:
        """Get older messages before the already-loaded recent messages

        Args:
            session_id: Session ID
            before_count: Number of recent messages to skip (already loaded)
            limit: Maximum number of older messages to return

        Returns:
            List of older messages in chronological order
        """
        # Get total count, then skip the recent ones and fetch older
        sql = """
        SELECT * FROM messages
        WHERE session_id = ? AND id NOT IN (
            SELECT id FROM messages WHERE session_id = ?
            ORDER BY created_at DESC LIMIT ?
        )
        ORDER BY created_at ASC LIMIT ?
        """
        rows = await self.db.fetch_all(sql, (session_id, session_id, before_count, limit))

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
        now = beijing_now().isoformat()

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
        now = beijing_now().isoformat()
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


class AgentMemoryRepository:
    """Agent-level long-term memory repository"""

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(
        self,
        agent_id: str,
        content: str,
        memory_type: str,
        importance: float = 0.5,
        session_id: Optional[str] = None,
        source: str = "auto",
        metadata: Optional[dict] = None
    ) -> str:
        """Create a new agent memory

        Args:
            agent_id: Agent ID
            content: Memory content
            memory_type: Type (preference / fact / event / summary)
            importance: Importance score 0.0-1.0
            session_id: Source session ID (optional)
            source: Source type (auto / manual)
            metadata: Optional metadata

        Returns:
            Memory ID
        """
        import uuid
        memory_id = str(uuid.uuid4())
        now = beijing_now().isoformat()
        metadata_json = json.dumps(metadata) if metadata else None

        sql = """
        INSERT INTO agent_memories (id, agent_id, session_id, content, memory_type,
                                     importance, access_count, source, metadata,
                                     created_at, last_accessed_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        """
        await self.db.execute(sql, (
            memory_id, agent_id, session_id, content, memory_type,
            importance, source, metadata_json, now, now
        ))
        await self.db.commit()

        return memory_id

    async def get_by_agent(
        self,
        agent_id: str,
        memory_type: Optional[str] = None,
        limit: int = 100
    ) -> List[dict]:
        """Get memories by agent ID

        Args:
            agent_id: Agent ID
            memory_type: Optional filter by type
            limit: Maximum results

        Returns:
            List of memories
        """
        if memory_type:
            sql = "SELECT * FROM agent_memories WHERE agent_id = ? AND memory_type = ? ORDER BY importance DESC, created_at DESC LIMIT ?"
            rows = await self.db.fetch_all(sql, (agent_id, memory_type, limit))
        else:
            sql = "SELECT * FROM agent_memories WHERE agent_id = ? ORDER BY importance DESC, created_at DESC LIMIT ?"
            rows = await self.db.fetch_all(sql, (agent_id, limit))

        return [self._row_to_dict(row) for row in rows]

    async def get_high_importance(self, agent_id: str, min_importance: float = 0.7) -> List[dict]:
        """Get high-importance memories for agent profile

        Args:
            agent_id: Agent ID
            min_importance: Minimum importance threshold

        Returns:
            List of high-importance memories
        """
        sql = """
        SELECT * FROM agent_memories
        WHERE agent_id = ? AND importance >= ?
        ORDER BY importance DESC
        """
        rows = await self.db.fetch_all(sql, (agent_id, min_importance))
        return [self._row_to_dict(row) for row in rows]

    async def update_access(self, memory_id: str) -> None:
        """Update access count and last_accessed_at

        Args:
            memory_id: Memory ID
        """
        now = beijing_now().isoformat()
        sql = """
        UPDATE agent_memories
        SET access_count = access_count + 1, last_accessed_at = ?
        WHERE id = ?
        """
        await self.db.execute(sql, (now, memory_id))
        await self.db.commit()

    async def update(self, memory_id: str, **kwargs) -> bool:
        """Update memory fields

        Args:
            memory_id: Memory ID
            **kwargs: Fields to update

        Returns:
            True if updated
        """
        if not kwargs:
            return False

        updates = []
        params = []
        for key, value in kwargs.items():
            if key in ("content", "importance", "memory_type", "metadata"):
                updates.append(f"{key} = ?")
                if key == "metadata" and isinstance(value, dict):
                    value = json.dumps(value)
                params.append(value)

        if not updates:
            return False

        params.append(memory_id)
        sql = f"UPDATE agent_memories SET {', '.join(updates)} WHERE id = ?"
        await self.db.execute(sql, tuple(params))
        await self.db.commit()
        return True

    async def delete(self, memory_id: str) -> bool:
        """Delete an agent memory

        Args:
            memory_id: Memory ID

        Returns:
            True if deleted
        """
        sql = "DELETE FROM agent_memories WHERE id = ?"
        await self.db.execute(sql, (memory_id,))
        await self.db.commit()
        return True

    async def delete_by_agent(self, agent_id: str) -> int:
        """Delete all memories for an agent

        Args:
            agent_id: Agent ID

        Returns:
            Number of deleted rows
        """
        sql = "DELETE FROM agent_memories WHERE agent_id = ?"
        await self.db.execute(sql, (agent_id,))
        await self.db.commit()
        return True

    async def get_memories_summary(self, agent_id: str, limit: int = 20) -> str:
        """Get a text summary of existing memories (for dedup in extraction)

        Args:
            agent_id: Agent ID
            limit: Max memories to include

        Returns:
            Text summary of memories
        """
        rows = await self.get_by_agent(agent_id, limit=limit)
        if not rows:
            return "（暂无已有记忆）"
        lines = []
        for row in rows:
            lines.append(f"- [{row['memory_type']}] {row['content']} (重要性: {row['importance']})")
        return "\n".join(lines)

    async def count(self, agent_id: str) -> int:
        """Count memories for an agent"""
        sql = "SELECT COUNT(*) as cnt FROM agent_memories WHERE agent_id = ?"
        row = await self.db.fetch_one(sql, (agent_id,))
        return row["cnt"] if row else 0

    async def search_similar_content(self, agent_id: str, content: str, limit: int = 5) -> List[dict]:
        """Search for memories with similar content (text-based fallback)

        Args:
            agent_id: Agent ID
            content: Content to search for
            limit: Maximum results

        Returns:
            List of similar memories
        """
        sql = """
        SELECT * FROM agent_memories
        WHERE agent_id = ? AND content LIKE ?
        ORDER BY importance DESC
        LIMIT ?
        """
        rows = await self.db.fetch_all(sql, (agent_id, f"%{content}%", limit))
        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row) -> dict:
        """Convert a database row to a dict"""
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "session_id": row.get("session_id"),
            "content": row["content"],
            "memory_type": row["memory_type"],
            "importance": row["importance"],
            "access_count": row["access_count"],
            "source": row.get("source", "auto"),
            "metadata": json.loads(row["metadata"]) if row.get("metadata") else None,
            "created_at": datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
            "last_accessed_at": datetime.fromisoformat(row["last_accessed_at"]) if row.get("last_accessed_at") else None,
        }
