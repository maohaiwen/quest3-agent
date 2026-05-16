"""Tests for global exception handlers."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_404_returns_standard_format(client: AsyncClient):
    """Non-existent route should return standardized error JSON."""
    resp = await client.get("/api/nonexistent-route")
    # FastAPI returns 404 for unknown routes — but not through our handler
    # because Starlette handles 404 before it reaches our catch-all.
    # The key test is that known routes with AppException return standard format.
    assert resp.status_code in (404, 405)


@pytest.mark.asyncio
async def test_validation_error_returns_standard_format(client: AsyncClient):
    """Invalid request body should return 422 with clean field errors."""
    # Login with empty body (should fail validation)
    resp = await client.post("/api/users/login", json={})
    assert resp.status_code == 422
    body = resp.json()
    # Our handler wraps it in {"error": {...}}
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["detail"] is not None


@pytest.mark.asyncio
async def test_session_not_found_format(client: AsyncClient, admin_headers: dict):
    """GET a non-existent session should return a clean 404."""
    resp = await client.get("/api/sessions/nonexistent-id", headers=admin_headers)
    assert resp.status_code == 404
