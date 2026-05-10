"""Tool plugin registry — knows how to register each tool service.

This module serves as the single source of truth for which tool services
exist and how to register their tools with the UnifiedToolManager.
It also supports re-registration after dependency installation.
"""
import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from app.tools.base import BaseToolService

if TYPE_CHECKING:
    from app.core.tool_manager import UnifiedToolManager

logger = logging.getLogger(__name__)


class ToolServiceDescriptor:
    """Describes a tool service and how to register it."""

    def __init__(
        self,
        service_name: str,
        service_cls: type,
        factory: Optional[callable] = None,
        enabled_by_default: bool = True,
    ):
        """
        Args:
            service_name: Unique name for this service
            service_cls: The BaseToolService subclass
            factory: Optional factory function that returns a service instance.
                     If None, service_cls() is used.
            enabled_by_default: Whether this service is auto-registered at startup
        """
        self.service_name = service_name
        self.service_cls = service_cls
        self.factory = factory
        self.enabled_by_default = enabled_by_default

    def create_instance(self) -> BaseToolService:
        if self.factory:
            return self.factory()
        return self.service_cls()


# ===== Service Registry =====

# Lazy-init: we populate this in register_all_services()
_service_descriptors: Dict[str, ToolServiceDescriptor] = {}


def register_all_services(tool_manager: "UnifiedToolManager") -> None:
    """Register all known tool services with the tool_manager.

    Services with unmet dependencies are registered with installed=False
    so they show up in the UI as available for installation.
    """
    from app.tools.filesystem import FileSystemToolService
    from app.tools.web_search import WebSearchToolService
    from app.tools.stock_backtest import StockBacktestToolService
    from app.config import settings

    # Define all services
    _service_descriptors.clear()

    _service_descriptors["FileSystem"] = ToolServiceDescriptor(
        service_name="FileSystem",
        service_cls=FileSystemToolService,
        enabled_by_default=True,
    )

    _service_descriptors["WebSearch"] = ToolServiceDescriptor(
        service_name="WebSearch",
        service_cls=WebSearchToolService,
        factory=lambda: WebSearchToolService(
            api_key=settings.WEB_SEARCH_API_KEY,
            base_url=settings.WEB_SEARCH_API_URL
        ),
        enabled_by_default=True,
    )

    _service_descriptors["FactorTest"] = ToolServiceDescriptor(
        service_name="FactorTest",
        service_cls=StockBacktestToolService,
        enabled_by_default=False,  # Not enabled by default — needs deps
    )

    # Register each service
    for name, desc in _service_descriptors.items():
        _register_service_tools(name, desc, tool_manager)


def _register_service_tools(
    name: str,
    desc: ToolServiceDescriptor,
    tool_manager: "UnifiedToolManager",
) -> None:
    """Register a single service's tools with the tool_manager."""
    is_installed = desc.service_cls.is_installed()

    # Only create instance if installed (or has no deps)
    instance = None
    if is_installed:
        try:
            instance = desc.create_instance()
        except Exception as e:
            logger.error(f"Failed to create service instance for {name}: {e}")
            is_installed = False

    # Get tool definitions
    tools = {}
    if instance:
        try:
            tools = instance.get_tools()
        except Exception as e:
            logger.warning(f"Failed to get tools from {name} instance: {e}")

    # If we can't get tools from instance, create stubs from class metadata
    if not tools:
        tools = _build_stub_tools(desc.service_cls)

    for tool_name, tool in tools.items():
        # Handle both MCPTool objects (from instance.get_tools()) and plain dicts (from TOOL_STUBS)
        if isinstance(tool, dict):
            description = tool.get("description", f"{name} tool")
            input_schema = tool.get("input_schema", {"type": "object", "properties": {}})
            handler = tool.get("handler") if is_installed else None
        else:
            description = getattr(tool, 'description', f"{name} tool")
            input_schema = getattr(tool, 'input_schema', {"type": "object", "properties": {}})
            handler = getattr(tool, 'handler', None) if is_installed else None

        tool_manager.register_local_tool(
            name=tool_name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            source="local",
            installed=is_installed,
            service_name=name,
            deps=desc.service_cls.deps,
        )

    logger.info(f"Registered service '{name}': installed={is_installed}, tools={list(tools.keys())}")


def _build_stub_tools(service_cls: type) -> Dict[str, Dict[str, Any]]:
    """Build stub tool entries for a not-installed service.

    Uses the TOOL_STUBS class attribute if defined, otherwise creates
    a single stub from service_name/description.

    Returns dict of tool_name -> {description, input_schema, handler=None}
    """
    # Check if the class defines TOOL_STUBS (static tool metadata)
    if hasattr(service_cls, 'TOOL_STUBS') and service_cls.TOOL_STUBS:
        return service_cls.TOOL_STUBS

    # Try instantiating — some services work without deps for metadata
    try:
        instance = service_cls()
        tools = instance.get_tools()
        if tools:
            # Return as plain dicts (strip handlers)
            result = {}
            for name, tool in tools.items():
                result[name] = {
                    "description": getattr(tool, 'description', f'{name} tool'),
                    "input_schema": getattr(tool, 'input_schema', {"type": "object", "properties": {}}),
                    "handler": None,  # No handler — not installed
                }
            return result
    except Exception:
        pass

    # Fallback: single stub
    svc_name = getattr(service_cls, 'service_name', service_cls.__name__)
    svc_desc = getattr(service_cls, 'service_description', '')
    return {
        svc_name: {
            "description": f"{svc_desc} (依赖未安装)" if svc_desc else f"{svc_name} tools (依赖未安装)",
            "input_schema": {"type": "object", "properties": {}},
            "handler": None,
        }
    }


async def reregister_service(service_name: str, tool_manager: "UnifiedToolManager") -> None:
    """Re-register a service's tools after its deps are installed.

    Called by UnifiedToolManager.install_service_deps() after pip install succeeds.
    """
    desc = _service_descriptors.get(service_name)
    if not desc:
        logger.error(f"Cannot reregister unknown service: {service_name}")
        return

    # Remove old tool entries
    to_remove = [
        name for name, tool_def in tool_manager._local_tools.items()
        if tool_def.service_name == service_name
    ]
    for name in to_remove:
        del tool_manager._local_tools[name]

    # Re-register with new instance
    _register_service_tools(service_name, desc, tool_manager)
    logger.info(f"Re-registered service '{service_name}' after install")


def get_service_descriptors() -> Dict[str, ToolServiceDescriptor]:
    """Get all registered service descriptors"""
    return _service_descriptors
