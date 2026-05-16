"""Tests for the /health endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200

    body = resp.json()
    assert "status" in body
    assert body["status"] == "healthy"
    assert "llm_configured" in body
    assert "vector_store_available" in body
