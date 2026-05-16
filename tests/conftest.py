"""Shared test fixtures for quest3-agent.

Provides:
- In-memory SQLite database for isolation
- FastAPI TestClient with the app configured for testing
- Auth headers for admin user (bypasses rate-limited login endpoint)
"""
import asyncio
from typing import AsyncGenerator, Generator

import pytest
from httpx import ASGITransport, AsyncClient

from app.database.connection import DatabaseConnection
from app.database.repositories import SessionRepository, MessageRepository, MemoryRepository
from app.container import ServiceContainer


# ---------------------------------------------------------------------------
# Event loop — needed for async fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database — fresh in-memory SQLite per test
# ---------------------------------------------------------------------------


@pytest.fixture
async def db() -> AsyncGenerator[DatabaseConnection, None]:
    """Provide a fresh in-memory database with schema initialized."""
    database = DatabaseConnection("sqlite+aiosqlite:///:memory:")
    await database.connect()
    await database.initialize_schema()
    yield database
    await database.disconnect()


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(db: DatabaseConnection) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client with a real in-memory database."""
    from app.main import app
    from app.api.deps import set_container

    # Build a container with the default setup, then swap the db
    container = ServiceContainer()
    container.setup()

    # Replace the db and repo instances directly on the object
    container.db = db
    container.session_repo = SessionRepository(db)
    container.message_repo = MessageRepository(db)
    container.memory_repo = MemoryRepository(db)

    # Wire user & settings services with the test db
    container.settings_service.set_db(db)
    container.user_service.set_db(db)

    # Ensure default admin user and settings
    await container.user_service.ensure_default_admin()
    await container.settings_service.ensure_default_settings()

    # Set container so get_db_sync() works
    set_container(container)
    app.state.container = container

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Auth helpers — generate token directly to avoid rate limiting
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_token() -> str:
    """Return a valid admin JWT access token (generated directly, no HTTP call)."""
    from app.core.security import create_access_token
    return create_access_token(subject="admin", role="admin")


@pytest.fixture
def admin_headers(admin_token: str) -> dict:
    """Return Authorization headers for admin user."""
    return {"Authorization": f"Bearer {admin_token}"}
