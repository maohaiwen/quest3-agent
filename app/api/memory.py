"""Memory management API endpoints"""
from fastapi import APIRouter, HTTPException
import logging

from app.models.agent_memory import (
    AgentMemoryCreate, AgentMemorySearchRequest,
    AgentMemorySearchResponse, AgentMemoryProfile, AgentMemoryStats
)
from app.models.memory import MemoryStoreResponse
from app.services.agent_memory_service import agent_memory_service
from app.services.vector_service import VectorService
from app.config import settings
from app.database.connection import DatabaseConnection
from app.database.repositories import AgentMemoryRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


def get_vector_service():
    from app.main import vector_service
    return vector_service


# ---- Agent-level long-term memory API ----

@router.post("/agent/store", response_model=MemoryStoreResponse)
async def store_agent_memory(request: AgentMemoryCreate):
    """Store content to agent-level long-term memory"""
    try:
        memory_id = await agent_memory_service.store_manual(
            agent_id=request.agent_id,
            content=request.content,
            memory_type=request.memory_type.value,
            importance=request.importance
        )
        return MemoryStoreResponse(memory_id=memory_id)
    except Exception as e:
        logger.error(f"Error storing agent memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/search", response_model=AgentMemorySearchResponse)
async def search_agent_memory(request: AgentMemorySearchRequest):
    """Search agent-level long-term memory"""
    try:
        results = await agent_memory_service.recall(
            agent_id=request.agent_id,
            query=request.query,
            n=request.n,
            min_importance=request.min_importance
        )
        return AgentMemorySearchResponse(
            results=results,
            query=request.query,
            count=len(results)
        )
    except Exception as e:
        logger.error(f"Error searching agent memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent/{agent_id}/profile", response_model=AgentMemoryProfile)
async def get_agent_memory_profile(agent_id: str):
    """Get agent memory profile (high-importance preferences and facts)"""
    try:
        return await agent_memory_service.get_agent_profile(agent_id)
    except Exception as e:
        logger.error(f"Error getting agent profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agent/{agent_id}/consolidate")
async def consolidate_agent_memory(agent_id: str):
    """Trigger memory consolidation for an agent"""
    try:
        stats = await agent_memory_service.consolidate(agent_id)
        return {"agent_id": agent_id, "consolidation_stats": stats}
    except Exception as e:
        logger.error(f"Error consolidating agent memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent/{agent_id}/stats", response_model=AgentMemoryStats)
async def get_agent_memory_stats(agent_id: str):
    """Get memory statistics for an agent"""
    try:
        return await agent_memory_service.get_stats(agent_id)
    except Exception as e:
        logger.error(f"Error getting agent memory stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/agent/{agent_id}/{memory_id}")
async def delete_agent_memory(agent_id: str, memory_id: str):
    """Delete a specific agent memory"""
    repo = AgentMemoryRepository(DatabaseConnection(settings.DATABASE_URL))
    try:
        await repo.delete(memory_id)
        # Also delete from ChromaDB
        vector_service = get_vector_service()
        if vector_service.is_available():
            try:
                vector_service.delete(agent_id, memory_id)
            except Exception:
                pass
        # Invalidate profile cache
        agent_memory_service._profile_cache.pop(agent_id, None)
        return {"message": "Agent memory deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting agent memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await repo.db.disconnect()
