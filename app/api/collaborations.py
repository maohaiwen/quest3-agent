"""Collaboration API endpoints - manage multi-agent collaboration configurations and execution"""
import asyncio
import json
import logging
import time
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, AsyncGenerator
from datetime import datetime

from app.models.collaboration import (
    CollaborationCreate, CollaborationUpdate, CollaborationResponse,
    CollaborationMode, ArtifactResponse, ArtifactType, TEMPLATES
)
from app.services.collaboration_service import collaboration_service
from app.services.collaboration_engine import collaboration_engine
from app.api.deps import get_db_sync


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

# ---------------------------------------------------------------------------
# Background task registry — tracks tasks that continue after client disconnects
# ---------------------------------------------------------------------------
_background_tasks: Dict[str, asyncio.Task] = {}

# ---------------------------------------------------------------------------
# Event persistence — stores execution events both in-memory (fast, for
# running tasks) and in the database (durable, survives restarts).
# In-memory cache is checked first; DB is the source of truth for completed tasks.
# ---------------------------------------------------------------------------
_event_store: Dict[str, List[Dict]] = {}        # task_id -> [event, ...]
_event_store_ts: Dict[str, float] = {}           # task_id -> last update timestamp
_EVENT_TTL = 7200  # 2 hours
# Debounce DB writes — don't write on every single event
_event_flush_pending: Dict[str, bool] = {}       # task_id -> dirty flag
_event_flush_interval = 3.0  # seconds between DB flushes for a given task
_event_flush_tasks: Dict[str, asyncio.Task] = {} # task_id -> flush timer task

# ---------------------------------------------------------------------------
# Human input — tracks tasks paused waiting for human input via the frontend.
# When a collaboration hits an is_human agent, the executor yields a
# waiting_for_human SSE event and blocks on the asyncio.Event here.
# The frontend calls POST /tasks/{id}/human-input to submit the move,
# which sets the result and wakes the executor.
# ---------------------------------------------------------------------------
_pending_human_inputs: Dict[str, Dict] = {}
# task_id -> {
#   "event": asyncio.Event(),
#   "role": str,
#   "agent_id": str,
#   "sandbox": Optional[Any],
#   "result": Optional[Dict],
#   "prompt": str,
# }


def _store_event(task_id: str, event: Dict):
    """Append an event to the in-memory store and mark for DB flush."""
    if task_id not in _event_store:
        _event_store[task_id] = []
    _event_store[task_id].append(event)
    _event_store_ts[task_id] = time.time()
    _event_flush_pending[task_id] = True


async def _flush_events_to_db(task_id: str):
    """Flush in-memory events for a task to the database.

    Writes to both events_json (legacy blob) and task_events (per-row table).
    """
    events = _event_store.get(task_id)
    if not events:
        return
    try:
        from app.utils.timezone import beijing_now
        db = get_db_sync()
        try:
            # 1. Write legacy events_json blob (backward compat)
            events_json = json.dumps(events, ensure_ascii=False)
            await db.execute(
                "UPDATE collaboration_tasks SET events_json = ? WHERE task_id = ?",
                (events_json, task_id),
            )

            # 2. Write per-row to task_events table (only new events)
            now = beijing_now().isoformat()
            for i, evt in enumerate(events):
                evt_type = evt.get("type", "unknown")
                evt_json = json.dumps(evt, ensure_ascii=False)
                await db.execute(
                    "INSERT OR IGNORE INTO task_events (task_id, seq, event_type, event_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (task_id, i, evt_type, evt_json, now),
                )

            await db.commit()
        except Exception as inner_e:
            logger.error(f"DB write failed in _flush_events_to_db: {inner_e}")
    except Exception as e:
        logger.error(f"Failed to flush events to DB for task {task_id}: {e}")


def _schedule_flush(task_id: str):
    """Schedule a debounced flush of events to DB."""
    if task_id in _event_flush_tasks and not _event_flush_tasks[task_id].done():
        return  # Already scheduled
    async def _flush_after_delay():
        await asyncio.sleep(_event_flush_interval)
        if _event_flush_pending.get(task_id):
            await _flush_events_to_db(task_id)
            _event_flush_pending.pop(task_id, None)
        _event_flush_tasks.pop(task_id, None)
    _event_flush_tasks[task_id] = asyncio.create_task(_flush_after_delay())


async def _get_events_persisted(task_id: str) -> List[Dict]:
    """Return events for a task — checks memory first, then DB."""
    # Check memory first (fast, has running-task data)
    mem_events = _event_store.get(task_id)
    if mem_events:
        return mem_events
    # Fall back to database
    try:
        db = get_db_sync()
        row = await db.fetch_one(
            "SELECT events_json FROM collaboration_tasks WHERE task_id = ?",
            (task_id,)
        )
        if row and row.get("events_json"):
            events = json.loads(row["events_json"])
            # Cache in memory for subsequent reads
            _event_store[task_id] = events
            _event_store_ts[task_id] = time.time()
            return events
    except Exception as e:
        logger.error(f"Failed to load events from DB for task {task_id}: {e}")
    return []


def _cleanup_event_store():
    """Remove entries older than TTL and flush any remaining dirty events."""
    now = time.time()
    expired = [tid for tid, ts in _event_store_ts.items() if now - ts > _EVENT_TTL]
    for tid in expired:
        # Flush to DB before removing from memory
        if _event_flush_pending.get(tid):
            # Can't await here (sync context), so just schedule it
            asyncio.create_task(_flush_events_to_db(tid))
        _event_store.pop(tid, None)
        _event_store_ts.pop(tid, None)
        _event_flush_pending.pop(tid, None)


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


@router.get("/sandboxes/list")
async def list_sandboxes():
    """List available sandbox types"""
    try:
        from app.sandboxes.registry import SandboxRegistry
        return {"sandboxes": SandboxRegistry.list_available()}
    except Exception as e:
        logger.error(f"Error listing sandboxes: {e}")
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
    """Execute a collaboration task with SSE streaming.

    If the client disconnects, the task continues in the background
    using the non-streaming execute() path.  Results are persisted to DB;
    the user can view them upon return.
    """
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
            """Generate SSE events.  On client disconnect, restart the
            task in the background via execute_stream()."""
            event_count = 0
            streaming_task_id = None
            try:
                # Send a ping immediately to confirm SSE connection is alive
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

                async for event in collaboration_engine.execute_stream(collab, input):
                    event_count += 1
                    data = json.dumps(event, ensure_ascii=False)
                    # Capture task_id from task_start event
                    if event.get("type") == "task_start" and not streaming_task_id:
                        streaming_task_id = event.get("task_id")
                    # Store event so user can review later
                    if streaming_task_id:
                        _store_event(streaming_task_id, event)
                        # Periodically flush events to DB (every ~10 events)
                        if event_count % 10 == 0:
                            _schedule_flush(streaming_task_id)
                    yield f"data: {data}\n\n"

                logger.info(f"SSE stream complete, {event_count} events sent")
                # Final flush — ensure all events are persisted
                if streaming_task_id:
                    await _flush_events_to_db(streaming_task_id)
                yield "data: [DONE]\n\n"

            except asyncio.CancelledError:
                # Client disconnected — continue execution in background
                logger.info(f"SSE client disconnected after {event_count} events, continuing in background")
                _run_in_background(collab_id, input, streaming_task_id)
                return

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
                "X-Accel-Buffering": "no",
            }
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing collaboration SSE: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _run_in_background(collab_id: str, input_text: str, existing_task_id: str = None):
    """Spawn a background asyncio.Task that continues the collaboration to
    completion using execute_stream(). Reuses the existing task record so
    no duplicate records are created.
    """
    async def _execute():
        bg_task_id = existing_task_id
        try:
            logger.info(f"Background execution starting for collab {collab_id}, reusing task {existing_task_id}")
            collab = await collaboration_service.get(collab_id)
            if not collab:
                logger.error(f"Background: collab {collab_id} not found")
                return

            # Set flags so execute_stream skips creating a new task record
            mode_handler = collaboration_engine.modes.get(collab.mode)
            if mode_handler and existing_task_id:
                mode_handler._skip_task_record = True
                mode_handler._shared_task_id = existing_task_id

            # Clear old in-memory events so background starts fresh
            if existing_task_id:
                _event_store.pop(existing_task_id, None)

            try:
                async for event in collaboration_engine.execute_stream(collab, input_text):
                    # Capture task_id if not already known
                    if event.get("type") == "task_start" and not bg_task_id:
                        bg_task_id = event.get("task_id")
                    # Skip task_start from sub-mode — record already exists
                    if event.get("type") == "task_start" and existing_task_id:
                        continue
                    # Store events for later replay
                    if bg_task_id:
                        _store_event(bg_task_id, event)
            finally:
                # Reset flags
                if mode_handler:
                    mode_handler._skip_task_record = False
                    mode_handler._shared_task_id = None

            logger.info(f"Background execution complete for collab {collab_id}")
            # Flush all events to DB
            if bg_task_id:
                await _flush_events_to_db(bg_task_id)

        except Exception as e:
            logger.error(f"Background execution error for collab {collab_id}: {e}", exc_info=True)
            if bg_task_id:
                # Mark the task as failed
                try:
                    from app.utils.timezone import beijing_now
                    db = get_db_sync()
                    await db.execute(
                        "UPDATE collaboration_tasks SET status = ?, output = ?, completed_at = ? WHERE task_id = ?",
                        ("failed", str(e), beijing_now().isoformat(), bg_task_id),
                    )
                    await db.commit()
                except Exception as db_err:
                    logger.error(f"Failed to mark background task {bg_task_id} as failed: {db_err}")
        finally:
            _background_tasks.pop(collab_id, None)
            _cleanup_event_store()

    # Avoid duplicate background tasks for the same collab
    if collab_id in _background_tasks and not _background_tasks[collab_id].done():
        logger.warning(f"Background task already running for collab {collab_id}, skipping")
        return

    task = asyncio.create_task(_execute())
    _background_tasks[collab_id] = task





@router.get("/tasks/{task_id}/events")
async def get_task_events(
    task_id: str,
    exclude_types: Optional[str] = Query(default=None, description="Comma-separated event types to exclude (e.g. 'agent_thinking')"),
    types: Optional[str] = Query(default=None, description="Comma-separated event types to include (only these)"),
    limit: int = Query(default=500, ge=1, le=5000, description="Max events to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
):
    """Return stored execution events for a task, with optional filtering and pagination.

    Tries the per-row task_events table first (fast, indexed).
    Falls back to the events_json blob for legacy tasks.
    """
    # Parse filter params
    exclude_set = set(exclude_types.split(",")) if exclude_types else set()
    include_set = set(types.split(",")) if types else set()

    # 1. Try task_events table (fast path)
    try:
        db = get_db_sync()

        # Check if task_events has data for this task
        count_row = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM task_events WHERE task_id = ?",
            (task_id,)
        )
        has_row_data = count_row and count_row["cnt"] > 0

        if has_row_data:
            # Build WHERE clause
            conditions = ["task_id = ?"]
            params = [task_id]

            if include_set:
                placeholders = ",".join(["?"] * len(include_set))
                conditions.append(f"event_type IN ({placeholders})")
                params.extend(include_set)
            elif exclude_set:
                placeholders = ",".join(["?"] * len(exclude_set))
                conditions.append(f"event_type NOT IN ({placeholders})")
                params.extend(exclude_set)

            where = " AND ".join(conditions)

            # Get total count (without limit/offset)
            total_row = await db.fetch_one(
                f"SELECT COUNT(*) as cnt FROM task_events WHERE {where}",
                tuple(params)
            )
            total = total_row["cnt"] if total_row else 0

            # Get filtered events with pagination
            rows = await db.fetch_all(
                f"SELECT seq, event_json FROM task_events WHERE {where} ORDER BY seq ASC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset)
            )

            events = []
            for row in rows:
                try:
                    events.append(json.loads(row["event_json"]))
                except (json.JSONDecodeError, TypeError):
                    pass

            return {"task_id": task_id, "events": events, "count": len(events), "total": total}

    except Exception as e:
        logger.error(f"Error reading task_events table for {task_id}: {e}")

    # 2. Fallback: read from events_json blob (legacy)
    all_events = await _get_events_persisted(task_id)

    # Apply filters in memory
    if include_set:
        all_events = [e for e in all_events if e.get("type") in include_set]
    elif exclude_set:
        all_events = [e for e in all_events if e.get("type") not in exclude_set]

    total = len(all_events)
    page = all_events[offset:offset + limit]

    return {"task_id": task_id, "events": page, "count": len(page), "total": total}


@router.post("/tasks/{task_id}/human-input")
async def submit_human_input(task_id: str, body: Dict[str, Any] = None):
    """Submit input for a human player node that is currently waiting.

    Body: {"action": "make_move", "params": {"move": "马三进五"}}
       or: {"action": "text", "content": "我同意方案A"}
    """
    if body is None:
        body = {}

    entry = _pending_human_inputs.get(task_id)
    if not entry:
        raise HTTPException(status_code=400, detail="No pending human input for this task")

    action = body.get("action", "text")

    if entry.get("sandbox") and action == "make_move":
        # Sandbox-based game — validate through sandbox
        sandbox = entry["sandbox"]
        role = entry["role"]
        params = body.get("params", {})
        move = params.get("move", params.get("content", ""))

        # Resolve the actual sandbox tool name.  The frontend always
        # sends "make_move" but different sandboxes use different tool
        # names (e.g. chinese_chess uses "make_move", werewolf uses
        # "night_action" / "vote" / "hunter_shoot").
        # If no sandbox tools are available (e.g. werewolf day_speak
        # phase where players speak freely), treat as free-text.
        sandbox_tools = entry.get("sandbox_tools", [])
        if not sandbox_tools:
            # No tools available — free-text input
            if not move:
                raise HTTPException(status_code=400, detail="No input content provided")
            result = {"success": True, "message": move}
        else:
            actual_action = sandbox_tools[0]
            # Frontend sends "move" but sandbox tools expect specific
            # param names like "target".  Pass both so any sandbox
            # can pick up whichever it needs.
            result = await sandbox.handle_action(
                "human", role, actual_action,
                move=move, target=move)
    else:
        # Free-text input (non-sandbox modes)
        content = body.get("content", body.get("params", {}).get("content", ""))
        if not content:
            raise HTTPException(status_code=400, detail="No input content provided")
        result = {"success": True, "message": content}

    if result.get("success"):
        entry["result"] = result
        entry["event"].set()

    return result


@router.get("/tasks/{task_id}/pending-human")
async def get_pending_human(task_id: str):
    """Check if a task is currently waiting for human input.

    Used by the frontend to restore the input panel after page reload.
    """
    entry = _pending_human_inputs.get(task_id)
    if not entry:
        return {"waiting": False}

    return {
        "waiting": True,
        "role": entry.get("role", ""),
        "agent_id": entry.get("agent_id", ""),
        "prompt": entry.get("prompt", ""),
        "sandbox_tools": entry.get("sandbox_tools", []),
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get collaboration task status"""
    try:
        db = get_db_sync()

        row = await db.fetch_one(
            "SELECT id, collaboration_id, task_id, input, output, status, started_at, completed_at FROM collaboration_tasks WHERE task_id = ?",
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
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a collaboration task and its artifacts"""
    try:
        db = get_db_sync()

        # Check task exists
        row = await db.fetch_one(
            "SELECT task_id, status FROM collaboration_tasks WHERE task_id = ?",
            (task_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        if row["status"] == "running":
            raise HTTPException(status_code=400, detail="Cannot delete a running task, wait for it to finish or interrupt first")

        # Delete task events first (largest table)
        await db.execute(
            "DELETE FROM task_events WHERE task_id = ?",
            (task_id,)
        )
        # Delete artifacts
        await db.execute(
            "DELETE FROM collaboration_artifacts WHERE task_id = ?",
            (task_id,)
        )
        # Delete task
        await db.execute(
            "DELETE FROM collaboration_tasks WHERE task_id = ?",
            (task_id,)
        )
        await db.commit()

        # Clean up in-memory event store
        _event_store.pop(task_id, None)
        _event_store_ts.pop(task_id, None)
        _event_flush_pending.pop(task_id, None)

        return {"success": True, "message": "Task deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{collab_id}/tasks")
async def list_collaboration_tasks(collab_id: str):
    """List all tasks for a collaboration"""
    try:
        from app.utils.timezone import beijing_now
        import json

        db = get_db_sync()

        # Auto-fix: mark running tasks older than 30 min as interrupted
        from datetime import timedelta
        cutoff = (beijing_now() - timedelta(minutes=30)).isoformat()
        await db.execute(
            """UPDATE collaboration_tasks
               SET status = 'interrupted', output = '运行超时，任务中断', completed_at = ?
               WHERE status = 'running' AND started_at < ?""",
            (beijing_now().isoformat(), cutoff),
        )
        await db.commit()

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

    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{collab_id}/artifacts")
async def list_artifacts(
    collab_id: str,
    round: Optional[int] = Query(default=None, description="Filter by iteration round"),
    type: Optional[str] = Query(default=None, description="Filter by artifact type (text/code/data/chart/file)"),
):
    """List artifacts for a collaboration, optionally filtered by round or type"""
    try:
        db = get_db_sync()

        conditions = ["collaboration_id = ?"]
        params = [collab_id]

        if round is not None:
            conditions.append("round = ?")
            params.append(round)

        if type is not None:
            conditions.append("artifact_type = ?")
            params.append(type)

        where = " AND ".join(conditions)
        rows = await db.fetch_all(
            f"SELECT * FROM collaboration_artifacts WHERE {where} ORDER BY round ASC, created_at ASC",
            tuple(params)
        )

        artifacts = []
        for row in rows:
            artifacts.append(ArtifactResponse(
                id=row["id"],
                collaboration_id=row["collaboration_id"],
                task_id=row.get("task_id"),
                round=row.get("round", 1),
                producer_agent_id=row.get("producer_agent_id", ""),
                producer_role=row.get("producer_role", ""),
                name=row["name"],
                artifact_type=ArtifactType(row["artifact_type"]),
                content=row["content"],
                metadata=json.loads(row.get("metadata_json", "{}")),
                created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(),
            ))

        return {"artifacts": [a.dict() for a in artifacts]}

    except Exception as e:
        logger.error(f"Error listing artifacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/artifacts")
async def list_task_artifacts(task_id: str):
    """List artifacts for a specific collaboration task"""
    try:
        db = get_db_sync()

        rows = await db.fetch_all(
            "SELECT * FROM collaboration_artifacts WHERE task_id = ? ORDER BY round ASC, created_at ASC",
            (task_id,)
        )

        artifacts = []
        for row in rows:
            artifacts.append(ArtifactResponse(
                id=row["id"],
                collaboration_id=row["collaboration_id"],
                task_id=row.get("task_id"),
                round=row.get("round", 1),
                producer_agent_id=row.get("producer_agent_id", ""),
                producer_role=row.get("producer_role", ""),
                name=row["name"],
                artifact_type=ArtifactType(row["artifact_type"]),
                content=row["content"],
                metadata=json.loads(row.get("metadata_json", "{}")),
                created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(),
            ))

        return {"artifacts": [a.dict() for a in artifacts]}

    except Exception as e:
        logger.error(f"Error listing task artifacts: {e}")
        raise HTTPException(status_code=500, detail=str(e))
