"""Memory management API endpoints"""
from fastapi import APIRouter, HTTPException, Depends
import logging

from app.models.memory import (
    MemoryStoreRequest, MemorySearchRequest,
    MemoryStoreResponse, MemorySearchResponse,
    MemoryItem
)
from app.database.repositories import MemoryRepository
from app.services.vector_service import VectorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


def get_memory_repo():
    from app.main import memory_repo
    return memory_repo


def get_vector_service():
    from app.main import vector_service
    return vector_service


@router.post("/store", response_model=MemoryStoreResponse)
async def store_memory(
    request: MemoryStoreRequest,
    memory_repo: MemoryRepository = Depends(get_memory_repo),
    vector_service: VectorService = Depends(get_vector_service)
):
    """Store content to long-term memory"""
    try:
        # Store in database
        memory_id = await memory_repo.create(
            session_id=request.session_id,
            content=request.content,
            metadata=request.metadata
        )

        # Store in vector store for search
        if vector_service.is_available():
            try:
                vector_service.add(
                    session_id=request.session_id,
                    content=request.content,
                    metadata=request.metadata or {}
                )
            except Exception as e:
                logger.warning(f"Failed to store in vector store: {e}")

        return MemoryStoreResponse(memory_id=memory_id)

    except Exception as e:
        logger.error(f"Error storing memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=MemorySearchResponse)
async def search_memory(
    request: MemorySearchRequest,
    vector_service: VectorService = Depends(get_vector_service)
):
    """Search long-term memory"""
    try:
        if not vector_service.is_available():
            return MemorySearchResponse(
                results=[],
                query=request.query,
                count=0
            )

        # Search in vector store
        results = vector_service.search(
            session_id=request.session_id,
            query=request.query,
            n_results=request.limit
        )

        # Format results
        memory_items = []
        for result in results:
            memory_items.append(MemoryItem(
                id=result.get("id", ""),
                session_id=request.session_id,
                content=result.get("content", ""),
                metadata=result.get("metadata"),
                created_at=None
            ))

        return MemorySearchResponse(
            results=memory_items,
            query=request.query,
            count=len(memory_items)
        )

    except Exception as e:
        logger.error(f"Error searching memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    memory_repo: MemoryRepository = Depends(get_memory_repo)
):
    """Delete memory item"""
    try:
        await memory_repo.delete(memory_id)
        return {"message": "Memory deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))
