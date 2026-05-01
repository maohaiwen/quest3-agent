"""Session management API endpoints"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List
import logging

from app.models.session import SessionCreate, SessionUpdate, SessionResponse, SessionCreateResponse
from app.database.repositories import SessionRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def get_session_repo():
    from app.main import session_repo
    return session_repo


@router.post("/create", response_model=SessionCreateResponse)
async def create_session(
    session_data: SessionCreate,
    session_repo: SessionRepository = Depends(get_session_repo)
):
    """Create a new chat session"""
    try:
        return await session_repo.create(session_data)
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list/all")
async def list_all_sessions(
    session_repo: SessionRepository = Depends(get_session_repo)
):
    """List all sessions"""
    from app.database.connection import DatabaseConnection
    from app.config import settings

    db = DatabaseConnection(settings.DATABASE_URL)
    await db.connect()

    try:
        sql = "SELECT * FROM sessions ORDER BY created_at DESC"
        rows = await db.fetch_all(sql)

        sessions = []
        for row in rows:
            # Count messages for each session
            count_sql = "SELECT COUNT(*) as count FROM messages WHERE session_id = ?"
            count_row = await db.fetch_one(count_sql, (row["id"],))
            message_count = count_row["count"] if count_row else 0

            sessions.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "title": row["title"] or f"会话 {row['id'][:8]}",
                "agent_id": row.get("agent_id"),
                "status": row["status"],
                "message_count": message_count,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            })

        return {"sessions": sessions}

    finally:
        await db.disconnect()


@router.get("/list/by-agent/{agent_id}")
async def list_sessions_by_agent(
    agent_id: str,
    session_repo: SessionRepository = Depends(get_session_repo)
):
    """List sessions for a specific agent"""
    from app.database.connection import DatabaseConnection
    from app.config import settings

    db = DatabaseConnection(settings.DATABASE_URL)
    await db.connect()

    try:
        sql = "SELECT * FROM sessions WHERE agent_id = ? ORDER BY created_at DESC"
        rows = await db.fetch_all(sql, (agent_id,))

        sessions = []
        for row in rows:
            # Count messages for each session
            count_sql = "SELECT COUNT(*) as count FROM messages WHERE session_id = ?"
            count_row = await db.fetch_one(count_sql, (row["id"],))
            message_count = count_row["count"] if count_row else 0

            sessions.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "title": row["title"] or f"会话 {row['id'][:8]}",
                "agent_id": row.get("agent_id"),
                "status": row["status"],
                "message_count": message_count,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            })

        return {"sessions": sessions}

    finally:
        await db.disconnect()


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    session_repo: SessionRepository = Depends(get_session_repo)
):
    """Get session by ID"""
    session = await session_repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/{session_id}/history")
async def get_session_history(
    session_id: str,
    session_repo: SessionRepository = Depends(get_session_repo)
):
    """Get session message history"""
    session = await session_repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await session_repo.get_history(session_id)
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role.value,
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
    }


@router.put("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    update_data: SessionUpdate,
    session_repo: SessionRepository = Depends(get_session_repo)
):
    """Update session"""
    session = await session_repo.update(session_id, update_data)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    session_repo: SessionRepository = Depends(get_session_repo)
):
    """Delete session"""
    await session_repo.delete(session_id)
    return {"message": "Session deleted successfully"}
