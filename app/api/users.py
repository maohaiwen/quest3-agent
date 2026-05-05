"""User management API endpoints"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

from app.services.user_service import user_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("/login")
async def login(request: Dict[str, Any]):
    """Authenticate user and return user info.

    Request body:
        username: Username
        password: Plain text password
    """
    try:
        username = request.get("username", "").strip()
        password = request.get("password", "")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password are required")

        user = await user_service.authenticate(username, password)

        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        return {
            "success": True,
            "user": user
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/logout")
async def logout():
    """Logout (client-side only, clears localStorage)."""
    return {"success": True}


@router.get("")
async def list_users():
    """List all users (admin only)."""
    try:
        users = await user_service.list_users()
        return {"users": users}
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_user(request: Dict[str, Any]):
    """Create a new user (admin only).

    Request body:
        username: Username
        password: Password
        role: User role (admin / user)
        current_user_role: Role of the requesting user (must be admin)
    """
    try:
        current_user_role = request.get("current_user_role", "user")
        if current_user_role != "admin":
            raise HTTPException(status_code=403, detail="Only admin can create users")

        username = request.get("username", "").strip()
        password = request.get("password", "")
        role = request.get("role", "user")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password are required")

        result = await user_service.create_user(username, password, role)

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Creation failed"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{user_id}")
async def update_user(user_id: str, request: Dict[str, Any]):
    """Update user (admin only).

    Request body:
        username: New username (optional)
        password: New password (optional)
        role: New role (optional)
        current_user_role: Role of the requesting user (must be admin)
    """
    try:
        current_user_role = request.get("current_user_role", "user")
        if current_user_role != "admin":
            raise HTTPException(status_code=403, detail="Only admin can update users")

        result = await user_service.update_user(
            user_id,
            username=request.get("username"),
            password=request.get("password"),
            role=request.get("role")
        )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Update failed"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{user_id}")
async def delete_user(user_id: str, current_user_role: str = "user"):
    """Delete user (admin only)."""
    try:
        if current_user_role != "admin":
            raise HTTPException(status_code=403, detail="Only admin can delete users")

        result = await user_service.delete_user(user_id)

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me")
async def get_current_user(username: str = ""):
    """Get current user info by username."""
    try:
        users = await user_service.list_users()
        for user in users:
            if user["username"] == username:
                return {"user": user}
        raise HTTPException(status_code=404, detail="User not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        raise HTTPException(status_code=500, detail=str(e))
