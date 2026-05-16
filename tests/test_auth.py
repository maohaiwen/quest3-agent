"""Tests for authentication and authorization."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    resp = await client.post("/api/users/login", json={
        "username": "admin",
        "password": "Admin123",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post("/api/users/login", json={
        "username": "admin",
        "password": "WrongPassword1",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_missing_fields(client: AsyncClient):
    resp = await client.post("/api/users/login", json={
        "username": "",
        "password": "",
    })
    # Either 422 (validation) or 401 — both acceptable
    assert resp.status_code in (401, 422)


@pytest.mark.asyncio
async def test_protected_endpoint_without_token(client: AsyncClient):
    """Admin-only endpoint should reject unauthenticated requests."""
    resp = await client.get("/api/users")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_with_valid_token(client: AsyncClient, admin_headers: dict):
    resp = await client.get("/api/users", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "users" in body


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient):
    # Login to get tokens
    login_resp = await client.post("/api/users/login", json={
        "username": "admin",
        "password": "Admin123",
    })
    refresh_token = login_resp.json()["refresh_token"]

    # Refresh
    resp = await client.post("/api/users/refresh", json={
        "refresh_token": refresh_token,
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_get_current_user(client: AsyncClient, admin_headers: dict):
    resp = await client.get("/api/users/me", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "admin"
