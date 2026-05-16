"""Tests for UserService business logic."""
import pytest

from app.database.connection import DatabaseConnection
from app.services.user_service import UserService


@pytest.fixture
async def user_service(db: DatabaseConnection) -> UserService:
    svc = UserService()
    svc.set_db(db)
    await svc.ensure_default_admin()
    return svc


@pytest.mark.asyncio
async def test_ensure_default_admin(user_service: UserService):
    """Default admin should already exist after fixture setup."""
    user = await user_service.get_user_by_username("admin")
    assert user is not None
    assert user["role"] == "admin"


@pytest.mark.asyncio
async def test_authenticate_admin(user_service: UserService):
    result = await user_service.authenticate("admin", "Admin123")
    assert result is not None
    assert result["username"] == "admin"


@pytest.mark.asyncio
async def test_authenticate_wrong_password(user_service: UserService):
    result = await user_service.authenticate("admin", "wrong")
    assert result is None


@pytest.mark.asyncio
async def test_create_user(user_service: UserService):
    result = await user_service.create_user("testuser", "TestPass123", "user")
    assert result["success"] is True
    assert result["user"]["username"] == "testuser"


@pytest.mark.asyncio
async def test_create_user_duplicate_username(user_service: UserService):
    await user_service.create_user("dupuser", "DupPass123", "user")
    result = await user_service.create_user("dupuser", "DupPass456", "user")
    assert result["success"] is False
    assert "already exists" in result["error"]


@pytest.mark.asyncio
async def test_create_user_weak_password(user_service: UserService):
    result = await user_service.create_user("weakuser", "short", "user")
    assert result["success"] is False
    assert "Password" in result["error"]


@pytest.mark.asyncio
async def test_delete_last_admin(user_service: UserService):
    """Cannot delete the last admin user."""
    admin = await user_service.get_user_by_username("admin")
    result = await user_service.delete_user(admin["id"])
    assert result["success"] is False
    assert "last admin" in result["error"]


@pytest.mark.asyncio
async def test_list_users(user_service: UserService):
    users = await user_service.list_users()
    assert len(users) >= 1
    # Password hashes should not be present
    for u in users:
        assert "password_hash" not in u
