"""FastAPI application entry point"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
import logging

from app.config import settings
from app.container import ServiceContainer
from app.api.deps import set_container
from app.core.logging import setup_logging

# Configure logging
setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting up application...")

    # Create and wire service container
    container = ServiceContainer()
    container.setup()
    app.state.container = container
    set_container(container)  # Enable get_db_sync() for non-request code

    try:
        # Initialize database
        await container.db.initialize_schema()
        logger.info("Database initialized")

        # Clean up stale "running" tasks left from previous server instance
        try:
            from app.utils.timezone import beijing_now
            now_str = beijing_now().isoformat()
            result = await container.db.execute(
                "UPDATE collaboration_tasks SET status = 'interrupted', output = '服务重启，任务中断', completed_at = ? WHERE status = 'running'",
                (now_str,)
            )
            await container.db.commit()
            if result and hasattr(result, 'rowcount') and result.rowcount > 0:
                logger.info(f"Marked {result.rowcount} stale running tasks as interrupted")
        except Exception as e:
            logger.warning(f"Could not clean up stale tasks: {e}")

        # Initialize settings and user services with DB connection
        container.settings_service.set_db(container.db)
        container.user_service.set_db(container.db)

        # Ensure default settings exist in database
        await container.settings_service.ensure_default_settings()
        logger.info("Settings initialized")

        # Ensure default admin user exists
        await container.user_service.ensure_default_admin()
        logger.info("Default admin user ensured")

        # Reload settings from database (DB values override .env)
        await settings.reload_from_db(container.db)
        logger.info("Settings loaded from database")

        # Reconfigure LLM service with DB-loaded settings
        container.llm_service.reconfigure()
        logger.info("LLM service reconfigured with database settings")


        # Check LLM configuration
        if not container.llm_service.is_configured():
            logger.warning("LLM service not configured. Please set the appropriate API key in .env file")

        # Check vector service
        if not container.vector_service.is_available():
            logger.warning("Vector store not available. Long-term memory search will be disabled")

        # Initialize MCP tools
        logger.info("Initializing MCP tools...")
        fs_tools = container.fs_tool_service.get_tools()
        logger.info(f"Loaded {len(fs_tools)} local file system tools")

        # Load MCP servers from database
        try:
            from app.database.mcp_schema import create_mcp_tables
            await create_mcp_tables(container.db)
            logger.info("MCP database tables initialized")
        except Exception as e:
            logger.warning(f"Could not initialize MCP tables: {e}")

        # Check for MCP server URL in environment
        mcp_server_url = getattr(settings, 'MCP_SERVER_URL', None)
        if mcp_server_url:
            logger.info(f"Connecting to MCP server: {mcp_server_url}")
            connected = await container.mcp_tool_manager.connect_to_mcp_server(mcp_server_url)
            if connected:
                logger.info("MCP server connected successfully")
            else:
                logger.warning("Failed to connect to MCP server")
        else:
            logger.info("No MCP server URL configured, using local tools only")

        # Load and connect MCP servers from database
        try:
            servers_from_db = await container.db.fetch_all("SELECT * FROM mcp_servers WHERE enabled = 1")
            logger.info(f"Found {len(servers_from_db)} enabled MCP servers in database")

            for server in servers_from_db:
                server_id = server['id']
                name = server.get('name', 'Unknown')
                url = server.get('url')

                try:
                    # Parse headers
                    headers = {}
                    if server.get('headers'):
                        import json
                        headers = json.loads(server.get('headers'))

                    # Create server config
                    from app.services.mcp_pool import MCPServerConfig
                    config = MCPServerConfig(
                        id=server_id,
                        name=name,
                        url=url,
                        description=server.get('description', ''),
                        priority=server.get('priority', 0),
                        enabled=server.get('enabled', True),
                        server_type=server.get('server_type', 'standard'),
                        headers=headers
                    )

                    logger.info(f"Connecting to MCP server from DB: {name}")
                    success = await container.mcp_client_pool.add_server(config)

                    if success:
                        logger.info(f"Successfully connected to MCP server: {name}")
                    else:
                        logger.warning(f"Failed to connect to MCP server: {name}")

                except Exception as e:
                    logger.error(f"Error connecting to MCP server {name}: {e}")

        except Exception as e:
            logger.warning(f"Could not load MCP servers from database: {e}")

        # Initialize agent registry for A2A protocol
        try:
            await container.agent_registry.initialize()
            logger.info("Agent registry initialized for A2A protocol")
        except Exception as e:
            logger.warning(f"Could not initialize agent registry: {e}")
        try:
            from app.api.skills import initialize_skills
            await initialize_skills()
            logger.info("Skill system initialized successfully")
        except Exception as e:
            logger.warning(f"Could not initialize skill system: {e}")

        logger.info("Application started successfully")

    except Exception as e:
        logger.error(f"Error during startup: {e}")
        raise

    # Start background data cleanup
    from app.services.cleanup_service import CleanupService
    cleanup_svc = CleanupService(
        db=container.db,
        retention_days=settings.SESSION_RETENTION_DAYS,
    )
    cleanup_svc.start(interval_hours=settings.CLEANUP_INTERVAL_HOURS)

    yield

    # Shutdown
    logger.info("Shutting down application...")

    # Stop cleanup service
    cleanup_svc.stop()

    # Close MCP client pool
    await container.mcp_client_pool.close_all()

    # Disconnect from MCP server
    if container.mcp_tool_manager.mcp_service.is_connected():
        await container.mcp_tool_manager.mcp_service.disconnect()

    await container.db.disconnect()
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Quest3 Agent",
    description="AI智能体聊天应用，支持多轮对话和长短期记忆",
    version="0.1.0",
    lifespan=lifespan
)

# Register global exception handlers
from app.core.exceptions import register_exception_handlers
register_exception_handlers(app)

# CORS middleware
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Import routers
from app.api import chat, sessions, memory, mcp, mcp_servers
from app.api import agents  # Import agents module
from app.api import skills  # Import skills module
from app.api import collaborations, a2a  # Import collaboration and A2A modules
from app.api import settings as settings_api  # Import settings module
from app.api import users as users_api  # Import users module
from app.api import tools as tools_api  # Import tools management module

# Include routers
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(memory.router)
app.include_router(mcp.router)
app.include_router(mcp_servers.router)
app.include_router(agents.router)
app.include_router(skills.router)
app.include_router(collaborations.router)
app.include_router(a2a.router)
app.include_router(settings_api.router)
app.include_router(users_api.router)
app.include_router(tools_api.router)

# Security headers middleware (pure ASGI — does not buffer streaming responses)
class SecurityHeadersMiddleware:
    """Adds standard security headers to all HTTP responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"x-xss-protection", b"1; mode=block"))
                headers.append(
                    (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                )
                headers.append(
                    (b"referrer-policy", b"strict-origin-when-cross-origin")
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)

# Mount static files with no-cache headers for development
# Using pure ASGI middleware instead of BaseHTTPMiddleware to avoid
# buffering streaming responses (SSE / event-stream)
class NoCacheMiddleware:
    """Pure ASGI middleware — adds no-cache headers for /static/ paths.
    Unlike BaseHTTPMiddleware, this does NOT buffer streaming responses.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_static = path.startswith("/static/")

        if not is_static:
            # Not a static file — pass through without touching the response
            await self.app(scope, receive, send)
            return

        # For static files, inject no-cache headers into the response
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-cache, no-store, must-revalidate"))
                headers.append((b"pragma", b"no-cache"))
                headers.append((b"expires", b"0"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(NoCacheMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/m")
async def mobile_page():
    """Mobile H5 page"""
    return RedirectResponse(url="/static/h5.html")


@app.get("/")
async def root():
    """Root endpoint - redirect to main page"""
    return RedirectResponse(url="/static/index.html")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    container = app.state.container
    return {
        "status": "healthy",
        "llm_configured": container.llm_service.is_configured(),
        "vector_store_available": container.vector_service.is_available(),
        "mcp_connected": container.mcp_tool_manager.mcp_service.is_connected()
    }


@app.get("/tools")
async def list_tools():
    """List available MCP tools"""
    container = app.state.container
    tools = container.mcp_tool_manager.get_tools_description()

    # Get detailed tool list
    all_tools = []
    for tool_name, tool in container.mcp_tool_manager.all_tools.items():
        all_tools.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "source": "mcp_server" if tool_name in container.mcp_tool_manager.mcp_service.tools else "local"
        })

    return {
        "mcp_connected": container.mcp_tool_manager.mcp_service.is_connected(),
        "total_tools": len(container.mcp_tool_manager.all_tools),
        "tools": all_tools,
        "tools_description": tools
    }
