"""Base classes for tool services"""
import importlib
import logging
from typing import Dict, Any, List, Optional

# Import MCPTool from mcp_service to avoid duplication
from app.services.mcp_service import MCPTool

logger = logging.getLogger(__name__)


class BaseToolService:
    """Base class for tool services

    Subclasses can declare pip dependencies via the `deps` class attribute.
    If dependencies are missing, the service registers as "not installed"
    and can be installed on demand via the tool management API.
    """

    # Override in subclass to declare pip dependencies
    # e.g. ["akshare", "scipy"]
    deps: List[str] = []

    # Human-readable name for the tool service (shown in UI)
    service_name: str = "Unknown"

    # Short description of what this service provides
    service_description: str = ""

    @classmethod
    def check_deps(cls) -> Dict[str, bool]:
        """Check which dependencies are missing.

        Returns:
            Dict mapping package name to True (installed) / False (missing)
        """
        result = {}
        for pkg in cls.deps:
            try:
                importlib.import_module(pkg)
                result[pkg] = True
            except ImportError:
                result[pkg] = False
        return result

    @classmethod
    def is_installed(cls) -> bool:
        """Check if all dependencies are installed"""
        if not cls.deps:
            return True
        return all(cls.check_deps().values())

    def get_tools(self) -> Dict[str, MCPTool]:
        """Get available tools from this service

        Returns:
            Dictionary of tool definitions
        """
        raise NotImplementedError("Subclasses must implement get_tools()")

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool by name

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            Tool result
        """
        tools = self.get_tools()
        if tool_name not in tools:
            raise ValueError(f"Tool '{tool_name}' not found in {self.__class__.__name__}")

        tool = tools[tool_name]
        if not tool.handler:
            raise ValueError(f"Tool '{tool_name}' has no handler")

        return await tool.handler(**arguments)
