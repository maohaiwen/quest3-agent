"""Settings service - manages application configuration from database"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from app.database.connection import DatabaseConnection
from app.config import settings

logger = logging.getLogger(__name__)

# Default settings definition: (key, default_value, description, group_name, value_type, editable)
DEFAULT_SETTINGS = [
    # LLM Configuration
    ("VOLCENGINE_API_KEY", "", "Volcengine API Key", "llm", "secret", 1),
    ("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3", "Volcengine API 地址", "llm", "string", 1),
    ("VOLCENGINE_MODEL", "doubao-seed-2.0-lite-260215", "模型名称", "llm", "string", 1),
    ("VOLCENGINE_DEFAULT_REASONING_EFFORT", "medium", "推理努力程度 (minimal/low/medium/high)", "llm", "string", 1),
    ("LLM_TEMPERATURE", "0.7", "LLM 温度参数（Agent 未单独配置时生效）", "llm", "number", 1),
    ("LLM_MAX_TOKENS", "8192", "LLM 最大输出 Token 数（Agent 未单独配置时生效）", "llm", "number", 1),

    # Memory Configuration
    ("MEMORY_MAX_TOKENS", "1000", "记忆最大 Token 数", "memory", "number", 1),
    ("MEMORY_MAX_RECENT_MESSAGES", "20", "工作记忆最大最近消息数", "memory", "number", 1),
    ("MEMORY_SUMMARY_THRESHOLD", "30", "触发摘要的消息数阈值", "memory", "number", 1),
    ("MEMORY_SUMMARY_KEEP_RECENT", "10", "摘要时保留的最近消息数", "memory", "number", 1),
    ("MEMORY_IMPORTANCE_THRESHOLD", "0.3", "记忆重要性阈值", "memory", "number", 1),

    # Search Configuration
    ("WEB_SEARCH_API_KEY", "", "火山引擎 Web Search API Key", "search", "secret", 1),
    ("WEB_SEARCH_API_URL", "https://open.feedcoopapi.com/search_api/web_search", "Web Search API 地址", "search", "string", 1),
]

# Keys that require service reconfiguration when changed
HOT_RELOAD_KEYS = {"VOLCENGINE_API_KEY", "VOLCENGINE_BASE_URL", "VOLCENGINE_MODEL",
                   "LLM_TEMPERATURE", "LLM_MAX_TOKENS"}


class SettingsService:
    """Service for managing application settings stored in database"""

    def __init__(self):
        self._db: Optional[DatabaseConnection] = None

    def set_db(self, db: DatabaseConnection):
        """Set database connection"""
        self._db = db

    async def ensure_default_settings(self):
        """Insert default settings into database if they don't exist.

        Called at application startup to seed the app_settings table.
        Existing values are never overwritten.
        """
        if not self._db:
            logger.error("Database not set for SettingsService")
            return

        now = datetime.utcnow().isoformat()
        inserted = 0
        for key, default_value, description, group_name, value_type, editable in DEFAULT_SETTINGS:
            existing = await self._db.fetch_one(
                "SELECT key FROM app_settings WHERE key = ?", (key,)
            )
            if not existing:
                await self._db.execute(
                    """INSERT INTO app_settings (key, value, default_value, description, group_name, value_type, editable, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (key, None, default_value, description, group_name, value_type, editable, now, now)
                )
                inserted += 1

        await self._db.commit()
        if inserted > 0:
            logger.info(f"Initialized {inserted} default settings")

    async def get_all_settings(self, group: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all settings, with secret values masked.

        Args:
            group: Optional filter by group name

        Returns:
            List of setting dicts
        """
        if not self._db:
            return []

        if group:
            rows = await self._db.fetch_all(
                "SELECT * FROM app_settings WHERE group_name = ? ORDER BY key", (group,)
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM app_settings ORDER BY group_name, key"
            )

        result = []
        for row in rows:
            setting = dict(row)
            # Resolve effective value: DB value > .env value > default
            setting["effective_value"] = await self._resolve_value(row)
            # Mask secret values
            if row["value_type"] == "secret":
                val = setting["effective_value"]
                if val and len(val) > 4:
                    setting["display_value"] = "****" + val[-4:]
                elif val:
                    setting["display_value"] = "****"
                else:
                    setting["display_value"] = ""
            else:
                setting["display_value"] = setting["effective_value"]
            result.append(setting)

        return result

    async def get_setting(self, key: str) -> Optional[str]:
        """Get a single setting's effective value.

        Priority: DB value > .env value > default value
        """
        if not self._db:
            return getattr(settings, key, None)

        row = await self._db.fetch_one(
            "SELECT * FROM app_settings WHERE key = ?", (key,)
        )
        if not row:
            return getattr(settings, key, None)

        return await self._resolve_value(row)

    async def update_settings(self, updates: Dict[str, Any], user_role: str = "user") -> Dict[str, Any]:
        """Batch update settings.

        Args:
            updates: Dict of key -> new_value
            user_role: User role, only admin can update

        Returns:
            Result dict with success status and changed keys
        """
        if user_role != "admin":
            return {"success": False, "error": "Only admin can modify settings"}

        if not self._db:
            return {"success": False, "error": "Database not available"}

        now = datetime.utcnow().isoformat()
        changed_keys = []
        needs_reconfigure = False

        for key, new_value in updates.items():
            row = await self._db.fetch_one(
                "SELECT * FROM app_settings WHERE key = ? AND editable = 1", (key,)
            )
            if not row:
                logger.warning(f"Setting key not found or not editable: {key}")
                continue

            # Convert value to string for storage
            str_value = str(new_value) if new_value is not None else None

            await self._db.execute(
                "UPDATE app_settings SET value = ?, updated_at = ? WHERE key = ?",
                (str_value, now, key)
            )
            changed_keys.append(key)

            if key in HOT_RELOAD_KEYS:
                needs_reconfigure = True

        await self._db.commit()

        # Hot reload: update settings singleton and reconfigure services
        if needs_reconfigure:
            await self._apply_hot_reload(changed_keys)

        return {"success": True, "changed_keys": changed_keys}

    async def is_initialized(self) -> bool:
        """Check if critical settings have been configured.

        Returns False if VOLCENGINE_API_KEY is empty (first-time setup needed).
        """
        api_key = await self.get_setting("VOLCENGINE_API_KEY")
        return bool(api_key)

    async def _resolve_value(self, row: dict) -> str:
        """Resolve effective value for a setting row.

        Priority: DB value > .env value > default value
        """
        if row["value"] is not None:
            return row["value"]

        # Try .env value via pydantic settings
        env_value = getattr(settings, row["key"], None)
        if env_value is not None and env_value != "":
            return str(env_value)

        # Fallback to default
        return row["default_value"] or ""

    async def _apply_hot_reload(self, changed_keys: List[str]):
        """Apply hot-reload for changed settings.

        Updates the global Settings singleton and reconfigures services.
        """
        logger.info(f"Hot-reloading settings: {changed_keys}")

        # Update settings singleton attributes
        for key in changed_keys:
            value = await self.get_setting(key)
            if value is not None:
                # Get the field type from Settings model to convert properly
                field_info = settings.model_fields.get(key)
                if field_info:
                    # Try to convert the string value to the field's type
                    try:
                        if field_info.annotation == bool:
                            typed_value = str(value).lower() in ("true", "1", "yes")
                        elif field_info.annotation == int:
                            typed_value = int(value)
                        elif field_info.annotation == float:
                            typed_value = float(value)
                        else:
                            typed_value = value
                        setattr(settings, key, typed_value)
                    except (ValueError, TypeError):
                        setattr(settings, key, value)

        # Reconfigure LLM service if LLM-related keys changed
        llm_keys = {"VOLCENGINE_API_KEY", "VOLCENGINE_BASE_URL", "VOLCENGINE_MODEL"}
        if any(k in llm_keys for k in changed_keys):
            try:
                from app.services.llm_service import llm_service
                llm_service.reconfigure()
                logger.info("LLM service reconfigured with new settings")
            except Exception as e:
                logger.error(f"Failed to reconfigure LLM service: {e}")


# Global settings service instance
settings_service = SettingsService()
