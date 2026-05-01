"""Base classes for tool services"""
from typing import Dict, Any

# Import MCPTool from mcp_service to avoid duplication
from app.services.mcp_service import MCPTool


class BaseToolService:
    """Base class for tool services"""

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
