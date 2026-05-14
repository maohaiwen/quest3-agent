"""Security utilities — JWT tokens, password hashing, auth dependencies"""
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing (bcrypt directly — avoids passlib compatibility issues)
# ---------------------------------------------------------------------------

HASH_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a hashed value.

    Supports both bcrypt (new) and SHA-256 (legacy) hashes for migration.
    """
    # Try bcrypt first
    if is_bcrypt_hash(hashed):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False

    # Fallback: legacy SHA-256 (for migration from old hash format)
    sha256_hash = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return sha256_hash == hashed


def is_bcrypt_hash(hashed: str) -> bool:
    """Check if a hash string is bcrypt format."""
    return hashed.startswith("$2b$") or hashed.startswith("$2a$")


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login", auto_error=False)


def create_access_token(
    subject: str,
    role: str = "user",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a short-lived access token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=HASH_ALGORITHM)


def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a long-lived refresh token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    payload = {
        "sub": subject,
        "type": "refresh",
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=HASH_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token.

    Raises:
        JWTError: if the token is invalid or expired.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[HASH_ALGORITHM])


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: extract and verify the current user from JWT.

    Returns:
        dict with "username" and "role" keys.

    Raises:
        HTTPException 401: if token is missing or invalid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        raise credentials_exception

    try:
        payload = decode_token(token)
        username: Optional[str] = payload.get("sub")
        token_type: str = payload.get("type", "")
        if username is None or token_type != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    role = payload.get("role", "user")
    return {"username": username, "role": role}


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[dict]:
    """Like get_current_user but returns None instead of 401 on failure.

    Useful for endpoints that work both with and without auth.
    """
    if token is None:
        return None
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        token_type = payload.get("type", "")
        if username and token_type == "access":
            return {"username": username, "role": payload.get("role", "user")}
    except JWTError:
        pass
    return None


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency: require admin role."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
