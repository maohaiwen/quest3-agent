"""User management API endpoints"""
import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    require_admin,
)
from app.services.user_service import user_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])

limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class RefreshRequest(BaseModel):
    refresh_token: str


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)
    role: str = "user"


class UpdateUserRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    role: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest):
    """Authenticate user and return JWT tokens."""
    try:
        user = await user_service.authenticate(body.username, body.password)

        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        access_token = create_access_token(subject=user["username"], role=user["role"])
        refresh_token = create_refresh_token(subject=user["username"])

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user={"id": user["id"], "username": user["username"], "role": user["role"]},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/refresh")
async def refresh_token(request: RefreshRequest):
    """Refresh access token using a valid refresh token."""
    from jose import JWTError

    try:
        payload = decode_token(request.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Look up user to get current role
        user = await user_service.get_user_by_username(username)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        access_token = create_access_token(subject=username, role=user["role"])
        return {"access_token": access_token, "token_type": "bearer"}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing token: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/logout")
async def logout():
    """Logout (client-side only, clears localStorage)."""
    return {"success": True}


@router.get("")
async def list_users(admin: dict = Depends(require_admin)):
    """List all users (admin only)."""
    try:
        users = await user_service.list_users()
        return {"users": users}
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("")
async def create_user(request: CreateUserRequest, admin: dict = Depends(require_admin)):
    """Create a new user (admin only)."""
    try:
        result = await user_service.create_user(request.username, request.password, request.role)

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Creation failed"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    admin: dict = Depends(require_admin),
):
    """Update user (admin only)."""
    try:
        result = await user_service.update_user(
            user_id,
            username=request.username,
            password=request.password,
            role=request.role,
        )

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Update failed"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    """Delete user (admin only)."""
    try:
        result = await user_service.delete_user(user_id)

        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user info from JWT token."""
    try:
        user = await user_service.get_user_by_username(current_user["username"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"user": user}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
