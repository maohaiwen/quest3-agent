"""Application configuration management"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # API Configuration
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API key")

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

    # Log Configuration
    LOG_LEVEL: str = Field(default="INFO", description="Log level")

    # LLM Configuration
    LLM_MODEL: str = Field(default="claude-3-5-sonnet-20241022", description="LLM model name")
    LLM_TEMPERATURE: float = Field(default=0.7, description="LLM temperature")
    LLM_MAX_TOKENS: int = Field(default=8192, description="Maximum tokens for LLM response")

    # Volcengine Configuration (for deep thinking)
    VOLCENGINE_API_KEY: str = Field(default="", description="Volcengine API key for deep thinking")
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


# Global settings instance
settings = Settings()
