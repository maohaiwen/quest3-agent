"""Base class for collaboration modes with shared database operations"""
import json
import logging
import uuid
from datetime import datetime
from app.utils.timezone import beijing_now
from typing import Dict, Any

from app.models.a2a import A2ATask, A2ATaskStatus, A2ATaskStatusState, A2AMessage, A2AMessageRole
from app.models.collaboration import CollaborationResponse
from app.database.connection import DatabaseConnection
from app.config import settings

logger = logging.getLogger(__name__)


class BaseCollaborationMode:
    """Base class for collaboration modes.

    Provides shared _create_task_record and _update_task_record so subclasses
    don't need to reimplement them.
    """

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        """Execute collaboration mode"""
        raise NotImplementedError

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        """Execute collaboration mode with SSE events streaming.
        Yields dicts: {"type": "...", ...}
        """
        # Default: run execute and yield a complete event
        task = await self.execute(collab, input_text)
        yield {
            "type": "task_complete",
            "task_id": task.id,
            "status": task.status.state.value,
            "output": task.output,
            "messages": [m.dict() for m in task.messages]
        }

    async def _create_task_record(self, collab_id: str, task: A2ATask):
        """Create task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            now = beijing_now().isoformat()
            await db.execute("""
            INSERT INTO collaboration_tasks
            (id, collaboration_id, task_id, input, output, status, messages_json, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                collab_id,
                task.id,
                task.input,
                task.output,
                task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                now,
                None
            ))
            await db.commit()
        finally:
            await db.disconnect()

    async def _update_task_record(self, task: A2ATask, completed: bool = False):
        """Update task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            completed_at = beijing_now().isoformat() if completed else None
            await db.execute("""
            UPDATE collaboration_tasks
            SET output = ?, status = ?, messages_json = ?, completed_at = ?
            WHERE task_id = ?
            """, (
                task.output,
                task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                completed_at,
                task.id
            ))
            await db.commit()
        finally:
            await db.disconnect()

    def _create_task(self, input_text: str) -> A2ATask:
        """Helper to create a standard A2ATask with RUNNING status"""
        return A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )
