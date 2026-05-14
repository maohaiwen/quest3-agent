"""Application configuration management"""
from typing import ClassVar, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings

    Supports hot-reload from database: call reload_from_db() to refresh
    values from the app_settings table. DB values take priority over .env.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # API Configuration
    # Volcengine is the primary LLM provider

    # Server Configuration
    APP_HOST: str = Field(default="0.0.0.0", description="Application host")
    APP_PORT: int = Field(default=8000, description="Application port")
    APP_DEBUG: bool = Field(default=True, description="Debug mode")

    # Database Configuration
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./quest3_agent.db",
        description="Database connection URL",
    )

    # Memory Configuration
    MEMORY_MAX_TOKENS: int = Field(default=1000, description="Maximum tokens for memory")
    MEMORY_VECTOR_DIMENSION: int = Field(default=1536, description="Vector dimension for memory")
    MEMORY_MAX_RECENT_MESSAGES: int = Field(default=20, description="Max recent messages in working memory")
    MEMORY_SUMMARY_THRESHOLD: int = Field(default=30, description="Message count to trigger summarization")
    MEMORY_SUMMARY_KEEP_RECENT: int = Field(default=10, description="Keep recent N messages when summarizing")
    MEMORY_AUTO_EXTRACT: bool = Field(default=True, description="Enable auto memory extraction on session end")
    MEMORY_IMPORTANCE_THRESHOLD: float = Field(default=0.3, description="Minimum importance for memory recall")
    MEMORY_DECAY_LAMBDA: float = Field(default=0.05, description="Memory importance decay rate")

    # Log Configuration
    LOG_LEVEL: str = Field(default="INFO", description="Log level")

    # LLM Configuration (generic — shared across providers)
    LLM_PROVIDER: str = Field(default="volcengine", description="LLM provider: volcengine, deepseek, openai_compatible")
    LLM_API_KEY: str = Field(default="", description="LLM API Key")
    LLM_BASE_URL: str = Field(default="https://ark.cn-beijing.volces.com/api/v3", description="LLM API 地址")
    LLM_MODEL: str = Field(default="doubao-seed-2.0-lite-260215", description="模型名称")
    LLM_TEMPERATURE: float = Field(default=0.7, description="LLM temperature")
    LLM_MAX_TOKENS: int = Field(default=8192, description="Maximum tokens for LLM response")
    LLM_REASONING_EFFORT: str = Field(default="medium", description="Reasoning effort: minimal/low/medium/high")

    # Legacy fields — kept for .env backward compat, merged into LLM_* at runtime
    VOLCENGINE_API_KEY: str = Field(default="", description="Legacy: use LLM_API_KEY")
    VOLCENGINE_BASE_URL: str = Field(default="", description="Legacy: use LLM_BASE_URL")
    VOLCENGINE_MODEL: str = Field(default="", description="Legacy: use LLM_MODEL")
    VOLCENGINE_DEFAULT_REASONING_EFFORT: str = Field(default="medium", description="Legacy: use LLM_REASONING_EFFORT")
    DEEPSEEK_API_KEY: str = Field(default="", description="Legacy: use LLM_API_KEY")
    DEEPSEEK_BASE_URL: str = Field(default="", description="Legacy: use LLM_BASE_URL")
    DEEPSEEK_MODEL: str = Field(default="", description="Legacy: use LLM_MODEL")

    # Web Search Configuration (Volcano Engine Web Search API)
    WEB_SEARCH_API_KEY: str = Field(default="", description="Volcano Engine Web Search API key")
    WEB_SEARCH_API_URL: str = Field(default="https://open.feedcoopapi.com/search_api/web_search", description="Web search API endpoint")

    # Security Configuration
    SECRET_KEY: str = Field(
        default="change-me-in-production-use-a-random-secret",
        description="Secret key for JWT signing — MUST be changed in production",
    )
    CORS_ORIGINS: str = Field(
        default="http://localhost:8000,http://127.0.0.1:8000",
        description="Comma-separated allowed CORS origins",
    )
    TOOL_SANDBOX_DIR: str = Field(
        default="./sandbox_workspace",
        description="Base directory for file system tool sandbox",
    )

    # MCP Configuration
    MCP_SERVER_URL: str = Field(default="", description="MCP server URL")

    # Skill Directories Configuration
    SKILLS_BASE_DIR: str = Field(default="./skills", description="Base directory for all skills")
    SKILLS_BUILTIN_DIR: str = Field(default="./skills/builtin", description="Built-in skills directory")
    SKILLS_USER_DIR: str = Field(default="./skills/user", description="User-defined skills directory")
    SKILLS_CACHED_DIR: str = Field(default="./skills/cached", description="Cached skills directory")

    # Provider default presets (not a settings field — class constant)
    PROVIDER_PRESETS: ClassVar[Dict[str, Dict[str, str]]] = {
        "volcengine": {
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
        },
        "openai_compatible": {
            "base_url": "",
        },
    }

    def effective_llm_api_key(self) -> str:
        """Resolve API key: LLM_API_KEY > matching provider's legacy key."""
        if self.LLM_API_KEY:
            return self.LLM_API_KEY
        # Only fall back to the legacy key of the CURRENT provider
        provider = self.LLM_PROVIDER
        if provider == "deepseek" and self.DEEPSEEK_API_KEY:
            return self.DEEPSEEK_API_KEY
        if provider == "volcengine" and self.VOLCENGINE_API_KEY:
            return self.VOLCENGINE_API_KEY
        return ""

    def effective_llm_base_url(self) -> str:
        """Resolve base URL: LLM_BASE_URL > legacy > provider preset."""
        if self.LLM_BASE_URL:
            return self.LLM_BASE_URL
        provider = self.LLM_PROVIDER
        if provider == "deepseek" and self.DEEPSEEK_BASE_URL:
            return self.DEEPSEEK_BASE_URL
        if provider == "volcengine" and self.VOLCENGINE_BASE_URL:
            return self.VOLCENGINE_BASE_URL
        preset = self.PROVIDER_PRESETS.get(provider, {})
        return preset.get("base_url", "")

    def effective_llm_model(self) -> str:
        """Resolve model: LLM_MODEL > legacy (current provider only) > provider preset."""
        if self.LLM_MODEL:
            return self.LLM_MODEL
        # Only fall back to the legacy model of the CURRENT provider
        provider = self.LLM_PROVIDER
        if provider == "deepseek" and self.DEEPSEEK_MODEL:
            return self.DEEPSEEK_MODEL
        if provider == "volcengine" and self.VOLCENGINE_MODEL:
            return self.VOLCENGINE_MODEL
        preset = self.PROVIDER_PRESETS.get(provider, {})
        return preset.get("model", "")

    def effective_llm_reasoning_effort(self) -> str:
        """Resolve reasoning effort: LLM_REASONING_EFFORT > legacy VOLCENGINE_DEFAULT_REASONING_EFFORT."""
        if self.LLM_REASONING_EFFORT:
            return self.LLM_REASONING_EFFORT
        if self.VOLCENGINE_DEFAULT_REASONING_EFFORT:
            return self.VOLCENGINE_DEFAULT_REASONING_EFFORT
        return "medium"

    async def reload_from_db(self, db):
        """Reload settings from database.

        DB values take priority over .env values. Only updates fields
        that have a non-null value in the database.

        Args:
            db: DatabaseConnection instance
        """
        try:
            rows = await db.fetch_all("SELECT key, value FROM app_settings WHERE value IS NOT NULL")
            for row in rows:
                key = row["key"]
                value = row["value"]
                if not hasattr(self, key):
                    continue
                # Get field type for proper conversion
                field_info = self.model_fields.get(key)
                if field_info:
                    try:
                        if field_info.annotation == bool:
                            typed_value = str(value).lower() in ("true", "1", "yes")
                        elif field_info.annotation == int:
                            typed_value = int(value)
                        elif field_info.annotation == float:
                            typed_value = float(value)
                        else:
                            typed_value = value
                        setattr(self, key, typed_value)
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to reload settings from DB: {e}")


# Global settings instance
settings = Settings()
