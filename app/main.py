"""FastAPI application entry point"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
import logging

from app.config import settings
from app.database.connection import DatabaseConnection
from app.database.repositories import SessionRepository, MessageRepository, MemoryRepository
from app.services.llm_service import LLMService
from app.services.session_working_memory import SessionWorkingMemory
from app.services.vector_service import VectorService
from app.services.agent_memory_service import agent_memory_service
from app.services.mcp_service import mcp_tool_manager
from app.tools.filesystem import FileSystemToolService
from app.tools.web_search import WebSearchToolService
from app.services.mcp_pool import mcp_client_pool
from app.services.planning_chat_service import planning_chat_service
from app.core.decision import decision_engine
from app.core.execution import execution_engine
from app.core.strategy_router import strategy_router
from app.services.settings_service import settings_service
from app.services.user_service import user_service
# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize services
db = DatabaseConnection(settings.DATABASE_URL)
session_repo = SessionRepository(db)
message_repo = MessageRepository(db)
memory_repo = MemoryRepository(db)
llm_service = LLMService()
memory_service = SessionWorkingMemory()
vector_service = VectorService()

# Wire agent_memory_service with vector_service
agent_memory_service.set_vector_service(vector_service)

# Initialize agent registry for A2A
from app.services.agent_registry import agent_registry

# Initialize MCP services
fs_tool_service = FileSystemToolService()
mcp_tool_manager.register_local_service("FileSystem", fs_tool_service)

# Initialize web search service (uses Volcano Engine Web Search API)
web_search_service = WebSearchToolService(
    api_key=settings.WEB_SEARCH_API_KEY,
    base_url=settings.WEB_SEARCH_API_URL
)
mcp_tool_manager.register_local_service("WebSearch", web_search_service)

# 使用统一工具管理器注册所有工具
from app.core.tool_manager import get_tool_manager
tool_manager = get_tool_manager()

# 注册文件系统工具
for tool_name, tool in fs_tool_service.get_tools().items():
    tool_manager.register_local_tool(
        name=tool_name,
        description=tool.description,
        input_schema=tool.input_schema,
        handler=tool.handler,
        source="local"
    )

# 注册网络搜索工具
for tool_name, tool in web_search_service.get_tools().items():
    tool_manager.register_local_tool(
        name=tool_name,
        description=tool.description,
        input_schema=tool.input_schema,
        handler=tool.handler,
        source="local"
    )

logger.info("All tools registered with UnifiedToolManager")

# Set LLM service for decision engine
decision_engine.set_llm_service(llm_service)

# Set LLM service for strategy router (it imports llm_service internally)
strategy_router.set_llm_client(llm_service)

# Register execution callback for streaming
async def execution_callback(event):
    """Execution callback for streaming events"""
    # This will be used by chat API to stream events
    pass

execution_engine.register_callback(execution_callback)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting up application...")

    try:
        # Initialize database
        await db.initialize_schema()
        logger.info("Database initialized")

        # Initialize settings and user services with DB connection
        settings_service.set_db(db)
        user_service.set_db(db)

        # Ensure default settings exist in database
        await settings_service.ensure_default_settings()
        logger.info("Settings initialized")

        # Ensure default admin user exists
        await user_service.ensure_default_admin()
        logger.info("Default admin user ensured")

        # Reload settings from database (DB values override .env)
        await settings.reload_from_db(db)
        logger.info("Settings loaded from database")

        # Check LLM configuration
        if not llm_service.is_configured():
            logger.warning("LLM service not configured. Please set VOLCENGINE_API_KEY in .env file")

        # Check vector service
        if not vector_service.is_available():
            logger.warning("Vector store not available. Long-term memory search will be disabled")

        # Initialize MCP tools
        logger.info("Initializing MCP tools...")
        fs_tools = fs_tool_service.get_tools()
        logger.info(f"Loaded {len(fs_tools)} local file system tools")

        # Load MCP servers from database
        try:
            from app.database.mcp_schema import create_mcp_tables
            await create_mcp_tables(db)
            logger.info("MCP database tables initialized")
        except Exception as e:
            logger.warning(f"Could not initialize MCP tables: {e}")

        # Check for MCP server URL in environment
        mcp_server_url = getattr(settings, 'MCP_SERVER_URL', None)
        if mcp_server_url:
            logger.info(f"Connecting to MCP server: {mcp_server_url}")
            connected = await mcp_tool_manager.connect_to_mcp_server(mcp_server_url)
            if connected:
                logger.info("MCP server connected successfully")
            else:
                logger.warning("Failed to connect to MCP server")
        else:
            logger.info("No MCP server URL configured, using local tools only")

        # Load and connect MCP servers from database
        try:
            servers_from_db = await db.fetch_all("SELECT * FROM mcp_servers WHERE enabled = 1")
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
                    success = await mcp_client_pool.add_server(config)

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
            await agent_registry.initialize()
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

    yield

    # Shutdown
    logger.info("Shutting down application...")

    # Close MCP client pool
    await mcp_client_pool.close_all()

    # Disconnect from MCP server
    if mcp_tool_manager.mcp_service.is_connected():
        await mcp_tool_manager.mcp_service.disconnect()

    await db.disconnect()
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Quest3 Agent",
    description="AI智能体聊天应用，支持多轮对话和长短期记忆",
    version="0.1.0",
    lifespan=lifespan
)

# Import routers
from app.api import chat, sessions, memory, mcp, mcp_servers
from app.api import agents  # Import agents module
from app.api import skills  # Import skills module
from app.api import collaborations, a2a  # Import collaboration and A2A modules
from app.api import settings as settings_api  # Import settings module
from app.api import users as users_api  # Import users module

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

# Mount static files with no-cache headers for development
from starlette.middleware.base import BaseHTTPMiddleware


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


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
    return {
        "status": "healthy",
        "llm_configured": llm_service.is_configured(),
        "vector_store_available": vector_service.is_available(),
        "mcp_connected": mcp_tool_manager.mcp_service.is_connected()
    }


@app.get("/tools")
async def list_tools():
    """List available MCP tools"""
    tools = mcp_tool_manager.get_tools_description()

    # Get detailed tool list
    all_tools = []
    for tool_name, tool in mcp_tool_manager.all_tools.items():
        all_tools.append({
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "source": "mcp_server" if tool_name in mcp_tool_manager.mcp_service.tools else "local"
        })

    return {
        "mcp_connected": mcp_tool_manager.mcp_service.is_connected(),
        "total_tools": len(mcp_tool_manager.all_tools),
        "tools": all_tools,
        "tools_description": tools
    }
