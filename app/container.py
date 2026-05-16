"""Service container — central registry for all application services.

Holds service instances and provides them to the rest of the application
via FastAPI dependency injection (see app.api.deps).

Usage in lifespan:
    container = ServiceContainer()
    container.setup()
    app.state.container = container

Usage in route handlers (via deps):
    def my_route(db: DatabaseConnection = Depends(get_db)):
        ...
"""
import logging

from app.config import settings
from app.database.connection import DatabaseConnection
from app.database.repositories import SessionRepository, MessageRepository, MemoryRepository

logger = logging.getLogger(__name__)


class ServiceContainer:
    """Central service container — holds all application service instances."""

    def __init__(self):
        # Core data layer
        self.db: DatabaseConnection | None = None
        self.session_repo: SessionRepository | None = None
        self.message_repo: MessageRepository | None = None
        self.memory_repo: MemoryRepository | None = None

        # Application services (singletons from their modules)
        self._llm_service = None
        self._memory_service = None
        self._vector_service = None
        self._agent_memory_service = None
        self._mcp_tool_manager = None
        self._mcp_client_pool = None
        self._settings_service = None
        self._user_service = None
        self._decision_engine = None
        self._execution_engine = None
        self._strategy_router = None
        self._planning_chat_service = None
        self._agent_registry = None
        self._tool_manager = None

        # Tool services
        self._fs_tool_service = None
        self._web_search_service = None
        self._stock_backtest_service = None

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def setup(self):
        """Wire up all services. Call once during application startup."""
        # Core data layer
        self.db = DatabaseConnection(settings.DATABASE_URL)
        self.session_repo = SessionRepository(self.db)
        self.message_repo = MessageRepository(self.db)
        self.memory_repo = MemoryRepository(self.db)

        # Session working memory
        from app.services.session_working_memory import SessionWorkingMemory
        self._memory_service = SessionWorkingMemory()

        # Vector service
        from app.services.vector_service import VectorService
        self._vector_service = VectorService()

        # Wire agent_memory_service with vector_service
        from app.services.agent_memory_service import agent_memory_service
        agent_memory_service.set_vector_service(self._vector_service)
        self._agent_memory_service = agent_memory_service

        # LLM service (module-level singleton)
        from app.services.llm_service import llm_service
        self._llm_service = llm_service

        # MCP services
        from app.services.mcp_service import mcp_tool_manager
        from app.services.mcp_pool import mcp_client_pool
        self._mcp_tool_manager = mcp_tool_manager
        self._mcp_client_pool = mcp_client_pool

        # Settings & user services
        from app.services.settings_service import settings_service
        from app.services.user_service import user_service
        self._settings_service = settings_service
        self._user_service = user_service

        # Core engines
        from app.core.decision import decision_engine
        from app.core.execution import execution_engine
        from app.core.strategy_router import strategy_router
        self._decision_engine = decision_engine
        self._execution_engine = execution_engine
        self._strategy_router = strategy_router

        # Planning chat service
        from app.services.planning_chat_service import planning_chat_service
        self._planning_chat_service = planning_chat_service

        # Agent registry
        from app.services.agent_registry import agent_registry
        self._agent_registry = agent_registry

        # Tool services
        from app.tools.filesystem import FileSystemToolService
        self._fs_tool_service = FileSystemToolService()
        self._mcp_tool_manager.register_local_service("FileSystem", self._fs_tool_service)

        from app.tools.web_search import WebSearchToolService
        self._web_search_service = WebSearchToolService(
            api_key=settings.WEB_SEARCH_API_KEY,
            base_url=settings.WEB_SEARCH_API_URL,
        )
        self._mcp_tool_manager.register_local_service("WebSearch", self._web_search_service)

        from app.tools.stock_backtest import StockBacktestToolService
        self._stock_backtest_service = StockBacktestToolService()
        self._mcp_tool_manager.register_local_service("FactorTest", self._stock_backtest_service)

        # Sandbox types
        from app.sandboxes.registry import SandboxRegistry
        from app.sandboxes.chinese_chess import ChineseChessSandbox
        from app.sandboxes.werewolf import WerewolfSandbox
        SandboxRegistry.register("chinese_chess", ChineseChessSandbox)
        SandboxRegistry.register("werewolf", WerewolfSandbox)
        logger.info("Sandbox types registered")

        # Unified tool manager + plugin registry
        from app.core.tool_manager import get_tool_manager
        from app.tools.plugin_registry import register_all_services
        self._tool_manager = get_tool_manager()
        register_all_services(self._tool_manager)
        logger.info("All tools registered with UnifiedToolManager (plugin system)")

        # Wire LLM into core engines
        self._decision_engine.set_llm_service(self._llm_service)
        self._strategy_router.set_llm_client(self._llm_service)

        # Register execution callback (placeholder)
        async def _execution_callback(event):
            pass

        self._execution_engine.register_callback(_execution_callback)

        logger.info("ServiceContainer setup complete")

    # ------------------------------------------------------------------
    # Convenience properties (lazy — most are already wired above)
    # ------------------------------------------------------------------

    @property
    def llm_service(self):
        return self._llm_service

    @property
    def memory_service(self):
        return self._memory_service

    @property
    def vector_service(self):
        return self._vector_service

    @property
    def agent_memory_service(self):
        return self._agent_memory_service

    @property
    def mcp_tool_manager(self):
        return self._mcp_tool_manager

    @property
    def mcp_client_pool(self):
        return self._mcp_client_pool

    @property
    def settings_service(self):
        return self._settings_service

    @property
    def user_service(self):
        return self._user_service

    @property
    def decision_engine(self):
        return self._decision_engine

    @property
    def execution_engine(self):
        return self._execution_engine

    @property
    def strategy_router(self):
        return self._strategy_router

    @property
    def planning_chat_service(self):
        return self._planning_chat_service

    @property
    def agent_registry(self):
        return self._agent_registry

    @property
    def tool_manager(self):
        return self._tool_manager

    @property
    def fs_tool_service(self):
        return self._fs_tool_service

    @property
    def web_search_service(self):
        return self._web_search_service

    @property
    def stock_backtest_service(self):
        return self._stock_backtest_service
