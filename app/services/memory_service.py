"""Memory service for managing conversation history"""
from typing import Optional, List
from collections import deque
import logging

from app.config import settings
from app.models.chat import MessageRole

logger = logging.getLogger(__name__)


class ConversationMemory:
    """In-memory conversation history management"""

    def __init__(self, max_tokens: int = 1000):
        """Initialize conversation memory

        Args:
            max_tokens: Maximum tokens to keep in memory
        """
        self.max_tokens = max_tokens
        self._messages: List[dict] = []

    def add_message(self, role: MessageRole, content: str) -> None:
        """Add a message to conversation history

        Args:
            role: Message role
            content: Message content
        """
        self._messages.append({
            "role": role.value,
            "content": content
        })

    def add_user_message(self, content: str) -> None:
        """Add a user message

        Args:
            content: Message content
        """
        self.add_message(MessageRole.USER, content)

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message

        Args:
            content: Message content
        """
        self.add_message(MessageRole.ASSISTANT, content)

    def get_messages(self) -> List[dict]:
        """Get all messages in history

        Returns:
            List of messages
        """
        return self._messages.copy()

    def get_last_n_messages(self, n: int) -> List[dict]:
        """Get last n messages

        Args:
            n: Number of messages

        Returns:
            List of messages
        """
        return self._messages[-n:] if n > 0 else []

    def clear(self) -> None:
        """Clear all messages"""
        self._messages.clear()

    def message_count(self) -> int:
        """Get message count

        Returns:
            Number of messages
        """
        return len(self._messages)


class MemoryService:
    """Service for managing conversation and long-term memory"""

    def __init__(self):
        """Initialize memory service"""
        self._sessions: dict[str, ConversationMemory] = {}
        self.max_tokens = settings.MEMORY_MAX_TOKENS

    def get_or_create_session_memory(self, session_id: str) -> ConversationMemory:
        """Get or create session memory

        Args:
            session_id: Session ID

        Returns:
            Conversation memory instance
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationMemory(max_tokens=self.max_tokens)

        return self._sessions[session_id]

    def add_message(self, session_id: str, role: MessageRole, content: str) -> None:
        """Add message to session memory

        Args:
            session_id: Session ID
            role: Message role
            content: Message content
        """
        memory = self.get_or_create_session_memory(session_id)
        memory.add_message(role, content)

    def get_conversation_history(self, session_id: str, limit: Optional[int] = None) -> List[dict]:
        """Get conversation history for session

        Args:
            session_id: Session ID
            limit: Optional limit on number of messages

        Returns:
            List of messages
        """
        memory = self.get_or_create_session_memory(session_id)

        if limit:
            return memory.get_last_n_messages(limit)

        return memory.get_messages()

    def load_from_db(self, session_id: str, db_messages: List[dict]) -> None:
        """Load messages from database into memory

        Args:
            session_id: Session ID
            db_messages: Messages from database
        """
        memory = self.get_or_create_session_memory(session_id)
        memory.clear()

        for msg in db_messages:
            role = MessageRole(msg["role"])
            content = msg["content"]
            memory.add_message(role, content)

    def clear_session(self, session_id: str) -> None:
        """Clear session memory

        Args:
            session_id: Session ID
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
