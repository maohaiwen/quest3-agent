"""Application configuration management"""
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

    # LLM Configuration (Volcengine)
    LLM_TEMPERATURE: float = Field(default=0.7, description="LLM temperature")
    LLM_MAX_TOKENS: int = Field(default=8192, description="Maximum tokens for LLM response")

    # Volcengine Configuration
    VOLCENGINE_API_KEY: str = Field(default="", description="Volcengine API key")
    VOLCENGINE_BASE_URL: str = Field(default="https://ark.cn-beijing.volces.com/api/v3", description="Volcengine API base URL")
    VOLCENGINE_MODEL: str = Field(default="doubao-seed-2.0-lite-260215", description="Volcengine model name")
    VOLCENGINE_DEFAULT_REASONING_EFFORT: str = Field(default="medium", description="Default reasoning effort: minimal/low/medium/high")

    # Web Search Configuration (Volcano Engine Web Search API)
    WEB_SEARCH_API_KEY: str = Field(default="", description="Volcano Engine Web Search API key")
    WEB_SEARCH_API_URL: str = Field(default="https://open.feedcoopapi.com/search_api/web_search", description="Web search API endpoint")

    # MCP Configuration
    MCP_SERVER_URL: str = Field(default="", description="MCP server URL")

    # Skill Directories Configuration
    SKILLS_BASE_DIR: str = Field(default="./skills", description="Base directory for all skills")
    SKILLS_BUILTIN_DIR: str = Field(default="./skills/builtin", description="Built-in skills directory")
    SKILLS_USER_DIR: str = Field(default="./skills/user", description="User-defined skills directory")
    SKILLS_CACHED_DIR: str = Field(default="./skills/cached", description="Cached skills directory")

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
