"""MCP (Model Context Protocol) service for tool calling"""
import asyncio
import json
import logging
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass
from enum import Enum

import httpx
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)


class MCPMessageType(str, Enum):
    """MCP message types"""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


@dataclass
class MCPTool:
    """MCP tool definition"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Optional[Callable] = None


class MCPService:
    """Service for managing MCP tool connections and invocations"""

    def __init__(self):
        """Initialize MCP service"""
        self.server_url: Optional[str] = None
        self.tools: Dict[str, MCPTool] = {}
        self.client: Optional[httpx.AsyncClient] = None
        self.connected = False

    async def connect(self, server_url: str, timeout: int = 30) -> bool:
        """Connect to MCP server

        Args:
            server_url: MCP server URL
            timeout: Connection timeout in seconds

        Returns:
            True if connection successful
        """
        self.server_url = server_url

        try:
            self.client = httpx.AsyncClient(timeout=timeout)

            # Test connection by listing tools
            tools = await self.list_tools()

            if tools:
                self.connected = True
                logger.info(f"Connected to MCP server: {server_url}")
                logger.info(f"Loaded {len(tools)} tools")
                return True
            else:
                logger.warning(f"Connected but no tools found on {server_url}")
                self.connected = True
                return True

        except Exception as e:
            logger.error(f"Failed to connect to MCP server {server_url}: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from MCP server"""
        if self.client:
            await self.client.aclose()
            self.client = None
        self.connected = False
        logger.info("Disconnected from MCP server")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from MCP server

        Returns:
            List of tool definitions
        """
        if not self.connected or not self.client:
            logger.warning("Not connected to MCP server")
            return []

        try:
            response = await self.client.post(
                f"{self.server_url}/tools/list",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            )
            response.raise_for_status()

            result = response.json()

            if "result" in result and "tools" in result["result"]:
                tools = result["result"]["tools"]

                # Cache tools
                self.tools = {}
                for tool in tools:
                    self.tools[tool["name"]] = MCPTool(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {})
                    )

                return tools

            return []

        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: int = 60
    ) -> Dict[str, Any]:
        """Call a tool on the MCP server

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            timeout: Request timeout in seconds

        Returns:
            Tool result
        """
        if not self.connected or not self.client:
            raise ValueError("Not connected to MCP server")

        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not found")

        try:
            response = await self.client.post(
                f"{self.server_url}/tools/call",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                },
                timeout=timeout
            )
            response.raise_for_status()

            result = response.json()

            if "result" in result:
                return result["result"]
            elif "error" in result:
                raise ValueError(f"Tool error: {result['error']}")
            else:
                return {}

        except httpx.TimeoutException:
            logger.error(f"Timeout calling tool {tool_name}")
            raise TimeoutError(f"Tool call timeout: {tool_name}")
        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}")
            raise

    def get_tool(self, tool_name: str) -> Optional[MCPTool]:
        """Get tool definition

        Args:
            tool_name: Tool name

        Returns:
            Tool definition or None
        """
        return self.tools.get(tool_name)

    def get_all_tools(self) -> Dict[str, MCPTool]:
        """Get all available tools

        Returns:
            Dictionary of all tools
        """
        return self.tools.copy()

    def is_connected(self) -> bool:
        """Check if connected to MCP server

        Returns:
            True if connected
        """
        return self.connected

    def get_tool_descriptions_for_llm(self) -> str:
        """Get tool descriptions formatted for LLM

        Returns:
            Formatted tool descriptions
        """
        if not self.tools:
            return "No tools available"

        descriptions = []
        for tool_name, tool in self.tools.items():
            desc = f"- {tool_name}: {tool.description}"
            if tool.input_schema:
                desc += f"\n  Parameters: {json.dumps(tool.input_schema, indent=2)}"
            descriptions.append(desc)

        return "\n\n".join(descriptions)


class MCPToolManager:
    """Manager for MCP tools from multiple sources"""

    def __init__(self):
        """Initialize MCP tool manager"""
        self.mcp_service = MCPService()
        self.local_services: Dict[str, Any] = {}
        self.all_tools: Dict[str, Any] = {}

    async def connect_to_mcp_server(self, server_url: str) -> bool:
        """Connect to an MCP server

        Args:
            server_url: MCP server URL

        Returns:
            True if successful
        """
        success = await self.mcp_service.connect(server_url)
        if success:
            self._refresh_tools()
        return success

    def register_local_service(self, name: str, service: Any):
        """Register a local tool service

        Args:
            name: Service name
            service: Service instance with get_tools() method
        """
        self.local_services[name] = service
        self._refresh_tools()

    def _refresh_tools(self):
        """Refresh the consolidated tool list"""
        self.all_tools = {}

        # Add MCP server tools
        if self.mcp_service.is_connected():
            self.all_tools.update(self.mcp_service.get_all_tools())

        # Add local service tools
        for service_name, service in self.local_services.items():
            if hasattr(service, 'get_tools'):
                tools = service.get_tools()
                self.all_tools.update(tools)

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """Call a tool (from MCP or local)

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        # First check MCP tools
        if self.mcp_service.is_connected() and tool_name in self.mcp_service.tools:
            return await self.mcp_service.call_tool(tool_name, arguments)

        # Then check local tools
        for service_name, service in self.local_services.items():
            if hasattr(service, 'get_tools'):
                tools = service.get_tools()
                if tool_name in tools:
                    tool = tools[tool_name]
                    if tool.handler:
                        return await tool.handler(**arguments)

        raise ValueError(f"Tool '{tool_name}' not found")

    def get_tools_description(self) -> str:
        """Get all tool descriptions for LLM

        Returns:
            Formatted tool descriptions
        """
        descriptions = []

        if self.mcp_service.is_connected():
            descriptions.append("## MCP Server Tools")
            descriptions.append(self.mcp_service.get_tool_descriptions_for_llm())
            descriptions.append("")

        for service_name, service in self.local_services.items():
            if hasattr(service, 'get_tools'):
                descriptions.append(f"## {service_name} Tools")
                tools = service.get_tools()
                for tool_name, tool in tools.items():
                    desc = f"- {tool_name}: {tool.description}"
                    if tool.input_schema:
                        desc += f"\n  Parameters: {json.dumps(tool.input_schema, indent=2)}"
                    descriptions.append(desc)
                descriptions.append("")

        return "\n".join(descriptions)


# Global MCP tool manager instance
mcp_tool_manager = MCPToolManager()
