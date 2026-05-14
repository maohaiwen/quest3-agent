"""User service - manages user accounts and authentication"""
import logging
import re
import uuid

from app.core.security import hash_password, verify_password, is_bcrypt_hash
from app.utils.timezone import beijing_now
from typing import Optional, Dict, Any, List

from app.database.connection import DatabaseConnection

logger = logging.getLogger(__name__)

# Password policy
MIN_PASSWORD_LENGTH = 8
PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).+$")


def _validate_password(password: str) -> Optional[str]:
    """Validate password against policy. Returns error message or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if not PASSWORD_PATTERN.match(password):
        return "Password must contain uppercase, lowercase, and a digit"
    return None


class UserService:
    """Service for managing users and authentication"""

    def __init__(self):
        self._db: Optional[DatabaseConnection] = None

    def set_db(self, db: DatabaseConnection):
        """Set database connection"""
        self._db = db

    async def ensure_default_admin(self):
        """Create default admin user if no users exist.

        Default credentials: admin / Admin123
        """
        if not self._db:
            logger.error("Database not set for UserService")
            return

        # Check if any users exist
        row = await self._db.fetch_one("SELECT COUNT(*) as cnt FROM app_users")
        if row and row["cnt"] > 0:
            return

        now = beijing_now().isoformat()
        user_id = str(uuid.uuid4())
        password_hash = hash_password("Admin123")

        await self._db.execute(
            """INSERT INTO app_users (id, username, password_hash, role, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, "admin", password_hash, "admin", now, now),
        )
        await self._db.commit()
        logger.info("Default admin user created (username: admin, password: Admin123)")

    async def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate a user.

        If the stored hash is legacy SHA-256, auto-migrates to bcrypt after
        successful verification.

        Args:
            username: Username
            password: Plain text password

        Returns:
            User dict if authenticated, None otherwise
        """
        if not self._db:
            return None

        row = await self._db.fetch_one(
            "SELECT * FROM app_users WHERE username = ?",
            (username,),
        )

        if not row:
            return None

        stored_hash = row["password_hash"]
        if not verify_password(password, stored_hash):
            return None

        # Auto-migrate legacy SHA-256 hash to bcrypt
        if not is_bcrypt_hash(stored_hash):
            new_hash = hash_password(password)
            now = beijing_now().isoformat()
            await self._db.execute(
                "UPDATE app_users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (new_hash, now, row["id"]),
            )
            await self._db.commit()
            logger.info(f"Auto-migrated password hash for user '{username}' to bcrypt")

        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
        }

    async def create_user(self, username: str, password: str, role: str = "user") -> Dict[str, Any]:
        """Create a new user.

        Args:
            username: Username (must be unique)
            password: Plain text password
            role: User role (admin / user)

        Returns:
            Created user dict
        """
        if not self._db:
            return {"success": False, "error": "Database not available"}

        # Check if username already exists
        existing = await self._db.fetch_one(
            "SELECT id FROM app_users WHERE username = ?", (username,)
        )
        if existing:
            return {"success": False, "error": "Username already exists"}

        if role not in ("admin", "user"):
            return {"success": False, "error": "Invalid role"}

        # Validate password
        pw_error = _validate_password(password)
        if pw_error:
            return {"success": False, "error": pw_error}

        now = beijing_now().isoformat()
        user_id = str(uuid.uuid4())
        password_hash = hash_password(password)

        await self._db.execute(
            """INSERT INTO app_users (id, username, password_hash, role, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, username, password_hash, role, now, now),
        )
        await self._db.commit()

        logger.info(f"User created: {username} (role: {role})")
        return {"success": True, "user": {"id": user_id, "username": username, "role": role}}

    async def list_users(self) -> List[Dict[str, Any]]:
        """List all users (without password hashes).

        Returns:
            List of user dicts
        """
        if not self._db:
            return []

        rows = await self._db.fetch_all(
            "SELECT id, username, role, created_at, updated_at FROM app_users ORDER BY created_at"
        )
        return [dict(row) for row in rows]

    async def update_user(self, user_id: str, **kwargs) -> Dict[str, Any]:
        """Update user fields.

        Args:
            user_id: User ID
            **kwargs: Fields to update (username, password, role)

        Returns:
            Result dict
        """
        if not self._db:
            return {"success": False, "error": "Database not available"}

        updates = []
        params = []

        if "username" in kwargs and kwargs["username"]:
            # Check uniqueness
            existing = await self._db.fetch_one(
                "SELECT id FROM app_users WHERE username = ? AND id != ?",
                (kwargs["username"], user_id),
            )
            if existing:
                return {"success": False, "error": "Username already exists"}
            updates.append("username = ?")
            params.append(kwargs["username"])

        if "password" in kwargs and kwargs["password"]:
            pw_error = _validate_password(kwargs["password"])
            if pw_error:
                return {"success": False, "error": pw_error}
            updates.append("password_hash = ?")
            params.append(hash_password(kwargs["password"]))

        if "role" in kwargs and kwargs["role"]:
            if kwargs["role"] not in ("admin", "user"):
                return {"success": False, "error": "Invalid role"}
            updates.append("role = ?")
            params.append(kwargs["role"])

        if not updates:
            return {"success": False, "error": "No fields to update"}

        now = beijing_now().isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(user_id)

        await self._db.execute(
            f"UPDATE app_users SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        await self._db.commit()

        return {"success": True}

    async def delete_user(self, user_id: str) -> Dict[str, Any]:
        """Delete a user.

        Args:
            user_id: User ID

        Returns:
            Result dict
        """
        if not self._db:
            return {"success": False, "error": "Database not available"}

        # Don't allow deleting the last admin
        user = await self._db.fetch_one(
            "SELECT role FROM app_users WHERE id = ?", (user_id,)
        )
        if not user:
            return {"success": False, "error": "User not found"}

        if user["role"] == "admin":
            admin_count = await self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM app_users WHERE role = 'admin'"
            )
            if admin_count and admin_count["cnt"] <= 1:
                return {"success": False, "error": "Cannot delete the last admin user"}

        await self._db.execute("DELETE FROM app_users WHERE id = ?", (user_id,))
        await self._db.commit()

        return {"success": True}

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID (without password hash)."""
        if not self._db:
            return None

        row = await self._db.fetch_one(
            "SELECT id, username, role, created_at, updated_at FROM app_users WHERE id = ?",
            (user_id,),
        )
        return dict(row) if row else None

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username (without password hash)."""
        if not self._db:
            return None

        row = await self._db.fetch_one(
            "SELECT id, username, role, created_at, updated_at FROM app_users WHERE username = ?",
            (username,),
        )
        return dict(row) if row else None


# Global user service instance
user_service = UserService()
