"""Collaboration API endpoints - manage multi-agent collaboration configurations and execution"""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, AsyncGenerator
from datetime import datetime

from app.models.collaboration import (
    CollaborationCreate, CollaborationUpdate, CollaborationResponse,
    CollaborationMode, TEMPLATES
)
from app.services.collaboration_service import collaboration_service
from app.services.collaboration_engine import collaboration_engine


class ExecuteRequest(BaseModel):
    """Request body for executing a collaboration"""
    input: str


class CreateFromTemplateRequest(BaseModel):
    """Request body for creating collaboration from template"""
    name: str
    agent_ids: Dict[str, str]
    agent_roles: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional role override per slot index: {'0': 'child', '1': 'child', ...}. "
                    "If not provided, roles are taken from template default_agents."
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collaborations", tags=["collaborations"])


@router.get("")
async def list_collaborations(enabled_only: bool = False):
    """List all collaboration configurations"""
    try:
        collabs = await collaboration_service.list(enabled_only=enabled_only)
        return {"collaborations": [c.dict() for c in collabs]}
    except Exception as e:
        logger.error(f"Error listing collaborations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=CollaborationResponse)
async def create_collaboration(data: CollaborationCreate):
    """Create a new collaboration configuration"""
    try:
        collab = await collaboration_service.create(data)
        return collab
    except Exception as e:
        logger.error(f"Error creating collaboration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{collab_id}", response_model=CollaborationResponse)
async def get_collaboration(collab_id: str):
    """Get collaboration configuration by ID"""
    try:
        collab = await collaboration_service.get(collab_id)
        if not collab:
            raise HTTPException(status_code=404, detail="Collaboration not found")
        return collab
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting collaboration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{collab_id}", response_model=CollaborationResponse)
async def update_collaboration(collab_id: str, data: CollaborationUpdate):
    """Update collaboration configuration"""
    try:
        collab = await collaboration_service.update(collab_id, data)
        if not collab:
            raise HTTPException(status_code=404, detail="Collaboration not found")
        return collab
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating collaboration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{collab_id}")
async def delete_collaboration(collab_id: str):
    """Delete collaboration configuration"""
    try:
        success = await collaboration_service.delete(collab_id)
        if not success:
            raise HTTPException(status_code=404, detail="Collaboration not found")
        return {"success": True, "message": "Collaboration deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting collaboration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates/list")
async def list_templates():
    """List all available collaboration templates"""
    try:
        templates = collaboration_service.list_templates()
        return {"templates": templates}
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/from-template/{template_key}")
async def create_from_template(template_key: str, request: CreateFromTemplateRequest):
    """Create a collaboration from a template"""
    try:
        collab = await collaboration_service.create_from_template(template_key, request.name, request.agent_ids, request.agent_roles)
        return collab
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating from template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{collab_id}/execute")
async def execute_collaboration(collab_id: str, request: ExecuteRequest):
    """Execute a collaboration task"""
    try:
        if not request.input:
            raise HTTPException(status_code=400, detail="input is required")

        result = await collaboration_engine.execute(collab_id, request.input)
        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing collaboration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{collab_id}/execute_sse")
async def execute_collaboration_sse(collab_id: str, input: str):
    """Execute a collaboration task with SSE streaming"""
    try:
        if not input:
            raise HTTPException(status_code=400, detail="input is required")

        # Get collaboration to verify it exists
        collab = await collaboration_service.get(collab_id)
        if not collab:
            raise HTTPException(status_code=404, detail="Collaboration not found")
        if not collab.enabled:
            raise HTTPException(status_code=400, detail="Collaboration is disabled")

        # Get mode handler for streaming
        from app.services.collaboration_engine import CollaborationMode
        mode_handler = collaboration_engine.modes.get(collab.mode)
        if not mode_handler:
            raise HTTPException(status_code=400, detail=f"Unsupported mode: {collab.mode}")

        async def generate():
            """Generate SSE events"""
            try:
                async for event in mode_handler.execute_stream(collab, input):
                    # Format as SSE
                    import json
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                # End stream
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"SSE stream error: {e}", exc_info=True)
                error_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
                yield f"data: {error_data}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable Nginx buffering
            }
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing collaboration SSE: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get collaboration task status"""
    try:
        from app.database.connection import DatabaseConnection
        from app.config import settings
        import json

        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            row = await db.fetch_one(
                "SELECT * FROM collaboration_tasks WHERE task_id = ?",
                (task_id,)
            )

            if not row:
                raise HTTPException(status_code=404, detail="Task not found")

            return {
                "task_id": row["task_id"],
                "collaboration_id": row["collaboration_id"],
                "input": row["input"],
                "output": row["output"],
                "status": row["status"],
                "messages": json.loads(row.get("messages_json", "[]")),
                "started_at": row.get("started_at"),
                "completed_at": row.get("completed_at"),
            }

        finally:
            await db.disconnect()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{collab_id}/tasks")
async def list_collaboration_tasks(collab_id: str):
    """List all tasks for a collaboration"""
    try:
        from app.database.connection import DatabaseConnection
        from app.config import settings
        import json

        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            rows = await db.fetch_all(
                "SELECT * FROM collaboration_tasks WHERE collaboration_id = ? ORDER BY started_at DESC",
                (collab_id,)
            )

            return {
                "tasks": [{
                    "task_id": row["task_id"],
                    "input": row["input"],
                    "output": row["output"],
                    "status": row["status"],
                    "started_at": row.get("started_at"),
                    "completed_at": row.get("completed_at"),
                } for row in rows]
            }

        finally:
            await db.disconnect()

    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))
