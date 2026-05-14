"""FastAPI dependency functions — pull services from request.app.state.container.

Usage in route handlers:
    from app.api.deps import get_db, get_session_repo

    @router.get("/")
    async def my_route(db: DatabaseConnection = Depends(get_db)):
        ...

Outside request context (background tasks, etc.):
    from app.api.deps import get_db_sync

    db = get_db_sync()
"""
from fastapi import Request

from app.database.connection import DatabaseConnection
from app.database.repositories import (
    SessionRepository,
    MessageRepository,
    MemoryRepository,
    AgentMemoryRepository,
)

# ---------------------------------------------------------------------------
# Module-level container reference — set once during app startup.
# Enables get_db_sync() for code running outside request context.
# ---------------------------------------------------------------------------
_container_ref = None


def set_container(container):
    """Store a reference to the ServiceContainer (called once during startup)."""
    global _container_ref
    _container_ref = container


def get_db_sync() -> DatabaseConnection:
    """Get the DatabaseConnection outside of request context.

    Use this in background tasks, event handlers, or any code that
    runs without a FastAPI Request object available.
    """
    if _container_ref is None:
        raise RuntimeError("ServiceContainer not initialized — call set_container() first")
    return _container_ref.db


def _container(request: Request):
    """Get the ServiceContainer from app state."""
    return request.app.state.container


# ---------------------------------------------------------------------------
# Core data layer
# ---------------------------------------------------------------------------

def get_db(request: Request) -> DatabaseConnection:
    return _container(request).db


def get_session_repo(request: Request) -> SessionRepository:
    return _container(request).session_repo


def get_message_repo(request: Request) -> MessageRepository:
    return _container(request).message_repo


def get_memory_repo(request: Request) -> MemoryRepository:
    return _container(request).memory_repo


# ---------------------------------------------------------------------------
# Application services
# ---------------------------------------------------------------------------

def get_llm_service(request: Request):
    return _container(request).llm_service


def get_memory_service(request: Request):
    return _container(request).memory_service


def get_vector_service(request: Request):
    return _container(request).vector_service


def get_agent_memory_service(request: Request):
    return _container(request).agent_memory_service


def get_mcp_tool_manager(request: Request):
    return _container(request).mcp_tool_manager


def get_mcp_client_pool(request: Request):
    return _container(request).mcp_client_pool


def get_settings_service(request: Request):
    return _container(request).settings_service


def get_user_service(request: Request):
    return _container(request).user_service


def get_decision_engine(request: Request):
    return _container(request).decision_engine


def get_execution_engine(request: Request):
    return _container(request).execution_engine


def get_strategy_router(request: Request):
    return _container(request).strategy_router


def get_planning_chat_service(request: Request):
    return _container(request).planning_chat_service


def get_agent_registry(request: Request):
    return _container(request).agent_registry


def get_tool_manager(request: Request):
    return _container(request).tool_manager


def get_fs_tool_service(request: Request):
    return _container(request).fs_tool_service


def get_web_search_service(request: Request):
    return _container(request).web_search_service


def get_stock_backtest_service(request: Request):
    return _container(request).stock_backtest_service
