"""Tests for session CRUD API endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_session(client: AsyncClient, admin_headers: dict):
    resp = await client.post(
        "/api/sessions/create",
        json={"title": "Test Session"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient, admin_headers: dict):
    # Create a session first
    create_resp = await client.post(
        "/api/sessions/create",
        json={"title": "List Test"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 200

    # List sessions
    resp = await client.get("/api/sessions/list/all", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "sessions" in body
    assert "total" in body
    assert body["total"] >= 1


@pytest.mark.asyncio
async def test_get_session_not_found(client: AsyncClient, admin_headers: dict):
    resp = await client.get("/api/sessions/nonexistent-id", headers=admin_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_pagination(client: AsyncClient, admin_headers: dict):
    # Create multiple sessions
    for i in range(3):
        await client.post(
            "/api/sessions/create",
            json={"title": f"Page Test {i}"},
            headers=admin_headers,
        )

    # Request page with limit=2
    resp = await client.get(
        "/api/sessions/list/all?limit=2&offset=0",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sessions"]) <= 2
    assert body["limit"] == 2
