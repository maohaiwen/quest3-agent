"""MCP client pool for managing multiple server connections"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import uuid
import json

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ConnectionStatus(str):
    """Connection status"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"


@dataclass
class MCPServerConfig:
    """MCP server configuration"""
    id: str
    name: str
    url: str
    description: str = ""
    priority: int = 0
    enabled: bool = True
    added_at: datetime = field(default_factory=datetime.utcnow)
    last_connected: Optional[datetime] = None
    status: str = ConnectionStatus.DISCONNECTED
    tool: int = 0
    headers: Dict[str, str] = field(default_factory=dict)
    server_type: str = "standard"  # "standard" or "streamable"
    tool_count: int = 0
    # Use short ID as prefix to avoid conflicts
    short_id: str = field(init=False)

    def __post_init__(self):
        # Generate a short prefix from ID (first 8 chars)
        self.short_id = self.id[:8] if len(self.id) > 8 else self.id

    def to_dict(self) -> dict:
        """Convert to dictionary

        Returns:
            Dictionary representation
        """
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "description": self.description,
            "priority": self.priority,
            "enabled": self.enabled,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "last_connected": self.last_connected.isoformat() if self.last_connected else None,
            "status": self.status,
            "tool_count": self.tool_count,
            "headers": {k: "***" for k in self.headers},  # 隐藏敏感信息
            "server_type": self.server_type
        }


@dataclass
class MCPServerConnection:
    """MCP server connection"""
    config: MCPServerConfig
    client: Optional[httpx.AsyncClient] = None
    tools: Dict[str, Any] = field(default_factory=dict)
    health_check_interval: int = 60  # seconds
    health_check_task: Optional[asyncio.Task] = None


class MCPClientPool:
    """Pool for managing multiple MCP server connections"""

    def __init__(self):
        """Initialize MCP client pool"""
        self.connections: Dict[str, MCPServerConnection] = {}
        self.lock = asyncio.Lock()
        self.health_check_running = False
        # Local tools registered via register_local_tool()
        self.local_tools: Dict[str, Any] = {}

    async def add_server(
        self,
        config: MCPServerConfig
    ) -> bool:
        """Add and connect to MCP server

        Args:
            config: Server configuration

        Returns:
            True if successful
        """
        async with self.lock:
            if config.id in self.connections:
                logger.warning(f"Server {config.id} already exists")
                return False

            connection = MCPServerConnection(config=config)

            try:
                await self._connect_server(connection)
                self.connections[config.id] = connection

                # Start health check
                self._start_health_check(connection)

                logger.info(f"Added MCP server: {config.name}")
                return True

            except Exception as e:
                logger.error(f"Failed to add server {config.name}: {e}")
                return False

    async def remove_server(self, server_id: str) -> bool:
        """Remove MCP server

        Args:
            server_id: Server ID

        Returns:
            True if removed (or if not found, which is OK)
        """
        async with self.lock:
            if server_id not in self.connections:
                # Server not in pool - may not be connected, but that's OK
                logger.info(f"Server {server_id} not found in pool (may not be connected)")
                return True

            connection = self.connections[server_id]

            # Stop health check
            if connection.health_check_task:
                connection.health_check_task.cancel()

            # Disconnect
            if connection.client:
                await connection.client.aclose()

            del self.connections[server_id]
            logger.info(f"Removed MCP server: {connection.config.name}")

            return True

    async def get_all_servers(self) -> List[dict]:
        """Get all servers

        Returns:
            List of server configurations
        """
        async with self.lock:
            return [
                connection.config.to_dict()
                for connection in self.connections.values()
            ]

    async def get_server(self, server_id: str) -> Optional[dict]:
        """Get server by ID

        Args:
            server_id: Server ID

        Returns:
            Server configuration or None
        """
        async with self.lock:
            connection = self.connections.get(server_id)
            if connection:
                return connection.config.to_dict()
            return None

    async def connect_server(self, server_id: str) -> bool:
        """Connect to MCP server

        Args:
            server_id: Server ID

        Returns:
            True if successful
        """
        async with self.lock:
            connection = self.connections.get(server_id)
            if not connection:
                logger.warning(f"Server {server_id} not found")
                return False

            try:
                await self._connect_server(connection)
                return True

            except Exception as e:
                logger.error(f"Failed to connect to server {server_id}: {e}")
                return False

    async def disconnect_server(self, server_id: str) -> bool:
        """Disconnect from MCP server

        Args:
            server_id: Server ID

        Returns:
            True if disconnected
        """
        async with self.lock:
            connection = self.connections.get(server_id)
            if not connection:
                logger.warning(f"Server {server_id} not found")
                return False

            if connection.client:
                await connection.client.aclose()
                connection.client = None
                connection.config.status = ConnectionStatus.DISCONNECTED

            logger.info(f"Disconnected from server {connection.config.name}")
            return True

    async def test_connection(self, server_id: str) -> dict:
        """Test MCP server connection

        Args:
            server_id: Server ID

        Returns:
            Test result
        """
        start_time = datetime.utcnow()

        async with self.lock:
            connection = self.connections.get(server_id)
            if not connection:
                return {
                    "success": False,
                    "error": "Server not found"
                }

            try:
                # Create test client with headers
                test_client = httpx.AsyncClient(
                    timeout=10.0,
                    headers=connection.config.headers
                )

                # Check server type for different test approach
                if connection.config.server_type == "streamable":
                    # For streamable servers, send to base URL with streaming
                    test_url = connection.config.url
                    request_body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

                    async with test_client.stream('POST', test_url, json=request_body) as response:
                        end_time = datetime.utcnow()
                        latency_ms = int((end_time - start_time).total_seconds() * 1000)

                        if response.status_code != 200:
                            await test_client.aclose()
                            return {
                                "success": False,
                                "connected": False,
                                "error": f"HTTP {response.status_code}"
                            }

                        # Parse streaming response to count tools
                        tool_count = 0
                        async for chunk in response.aiter_bytes():
                            if chunk:
                                text = chunk.decode('utf-8')
                                for line in text.strip().split('\n'):
                                    if line.strip():
                                        try:
                                            result = json.loads(line)
                                            if "result" in result and "tools" in result["result"]:
                                                tool_count = len(result["result"]["tools"])
                                        except:
                                            pass

                        await test_client.aclose()

                        return {
                            "success": True,
                            "connected": True,
                            "latency_ms": latency_ms,
                            "tool_count": tool_count
                        }
                else:
                    # For standard servers, append /tools/list
                    test_url = f"{connection.config.url}/tools/list"

                    # Test by listing tools
                    response = await test_client.post(
                        test_url,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                    )

                    await test_client.aclose()

                    end_time = datetime.utcnow()
                    latency_ms = int((end_time - start_time).total_seconds() * 1000)

                    if response.status_code == 200:
                        result = response.json()
                        tool_count = 0
                        if "result" in result and "tools" in result["result"]:
                            tool_count = len(result["result"]["tools"])

                        return {
                            "success": True,
                            "connected": True,
                            "latency_ms": latency_ms,
                            "tool_count": tool_count
                        }
                    else:
                        return {
                            "success": False,
                            "connected": False,
                            "error": f"HTTP {response.status_code}"
                        }

            except Exception as e:
                end_time = datetime.utcnow()
                latency_ms = int((end_time - start_time).total_seconds() * 1000)

                return {
                    "success": False,
                    "connected": False,
                    "latency_ms": latency_ms,
                    "error": str(e)
                }

    async def get_all_tools(self) -> Dict[str, Any]:
        """Get tools from all connected servers

        Returns:
            Dictionary of all tools
        """
        all_tools = {}

        # Add local tools first (higher priority, no prefix)
        logger.info(f"get_all_tools: local_tools has {len(self.local_tools)} tools: {list(self.local_tools.keys())}")
        for tool_name, tool in self.local_tools.items():
            all_tools[tool_name] = tool.copy()
            all_tools[tool_name]["name"] = tool_name  # Use original name without prefix

        # Add MCP server tools
        async with self.lock:
            for server_id, connection in self.connections.items():
                if connection.config.status == ConnectionStatus.CONNECTED:
                    # Use short_id as prefix to avoid encoding issues
                    prefix = connection.config.short_id
                    for tool_name, tool in connection.tools.items():
                        prefixed_name = f"{prefix}_{tool_name}"
                        all_tools[prefixed_name] = {
                            "name": prefixed_name,
                            "original_name": tool_name,
                            "server_id": server_id,
                            "server_name": connection.config.name,
                            "description": tool.get("description", ""),
                            "input_schema": tool.get("inputSchema", {}),
                            "source": "mcp"
                        }

        return all_tools

    def register_local_tool(self, tool_name: str, tool_def: Dict[str, Any]):
        """Register a local tool (not from MCP server)

        Args:
            tool_name: Tool name
            tool_def: Tool definition dict with name, description, input_schema, handler
        """
        self.local_tools[tool_name] = {
            "name": tool_name,
            "original_name": tool_def.get("name", tool_name),
            "description": tool_def.get("description", ""),
            "input_schema": tool_def.get("input_schema", {}),
            "handler": tool_def.get("handler"),
            "source": "local"
        }
        logger.info(f"Registered local tool: {tool_name}")

    async def call_local_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a local tool by name

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if tool_name not in self.local_tools:
            raise ValueError(f"Local tool '{tool_name}' not found")

        tool = self.local_tools[tool_name]
        handler = tool.get("handler")
        if not handler:
            raise ValueError(f"Local tool '{tool_name}' has no handler")

        return await handler(**arguments)

    def get_local_tools(self) -> Dict[str, Any]:
        """Get all local tools

        Returns:
            Dictionary of local tools
        """
        return self.local_tools.copy()

    def _get_server_prefix(self, server_name: str) -> str:
        """Get server prefix for tool name

        Args:
            server_name: Server name

        Returns:
            Normalized prefix
        """
        # Handle potential encoding issues
        try:
            import unicodedata
            normalized = server_name.replace(" ", "_").lower()
            # Try to normalize unicode characters
            normalized = unicodedata.normalize('NFKD', normalized)
            # Filter out non-ASCII characters for reliability
            import re
            normalized = re.sub(r'[^\x00-\x7f]', '', normalized)
            return normalized
        except Exception as e:
            # Fallback to simple replacement
            return server_name.replace(" ", "_").lower()

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: int = 60,
        server_id: Optional[str] = None
    ) -> Any:
        """Call a tool

        Args:
            tool_name: Tool name (may have server prefix)
            arguments: Tool arguments
            timeout: Request timeout
            server_id: Optional server ID to call tool on specific server

        Returns:
            Tool result
        """
        # If server_id is provided, call tool on that server
        if server_id:
            connection = self.connections.get(server_id)
            if not connection:
                raise ValueError(f"Server {server_id} not connected")
            # Don't check tool_name here since it might have prefix
            return await self._call_server_tool(connection, tool_name, arguments, timeout)

        # Check if tool_name has a server prefix (e.g., "1693271f_execute_code")
        server_prefix_found = False
        if "_" in tool_name:
            parts = tool_name.split("_", 1)
            server_prefix = parts[0]
            actual_tool_name = parts[1]

            # Find matching server by short_id
            async with self.lock:
                for server_id, connection in self.connections.items():
                    if connection.config.short_id == server_prefix:
                        if connection.client:
                            logger.debug(f"Found matching server: {connection.config.name} (short_id={connection.config.short_id})")
                            # Use actual_tool_name (original_name without prefix) when calling
                            server_prefix_found = True
                            return await self._call_server_tool(
                                connection,
                                actual_tool_name,
                                arguments,
                                timeout
                            )

        # If no server prefix matched or tool_name has no prefix, try local tools
        if tool_name in self.local_tools:
            logger.info(f"call_tool: Found '{tool_name}' in local_tools, calling it")
            return await self.call_local_tool(tool_name, arguments)
        else:
            logger.warning(f"call_tool: Tool '{tool_name}' not found in local_tools. Available: {list(self.local_tools.keys())}")

        raise ValueError(f"Tool '{tool_name}' not found")

    async def reconnect_all(self):
        """Reconnect all servers"""
        async with self.lock:
            for server_id, connection in self.connections.items():
                try:
                    await self._connect_server(connection)
                    logger.info(f"Reconnected to server {connection.config.name}")
                except Exception as e:
                    logger.error(f"Failed to reconnect to server {connection.config.name}: {e}")

    async def _connect_server(self, connection: MCPServerConnection):
        """Connect to MCP server

        Args:
            connection: Server connection
        """
        connection.config.status = ConnectionStatus.CONNECTING

        # Create client with default headers
        connection.client = httpx.AsyncClient(
            timeout=30.0,
            headers=connection.config.headers
        )

        # Check server type and connect accordingly
        if connection.config.server_type == "streamable":
            # Connect to streamable HTTP endpoint (like Aliyun)
            await self._connect_streamable_server(connection)
        else:
            # Connect to standard MCP server
            await self._connect_standard_server(connection)

    async def _connect_standard_server(self, connection: MCPServerConnection):
        """Connect to standard MCP server

        Args:
            connection: Server connection
        """
        # List tools to establish connection
        response = await connection.client.post(
            f"{connection.config.url}/tools/list",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        response.raise_for_status()

        result = response.json()

        if "result" in result and "tools" in result["result"]:
            connection.tools = {
                tool["name"]: tool
                for tool in result["result"]["tools"]
            }
            connection.config.tool_count = len(connection.tools)
            connection.config.status = ConnectionStatus.CONNECTED
            connection.config.last_connected = datetime.utcnow()

            logger.info(
                f"Connected to {connection.config.name}, "
                f"loaded {len(connection.tools)} tools"
            )
        else:
            raise ValueError("Invalid MCP response")

    async def _connect_streamable_server(self, connection: MCPServerConnection):
        """Connect to streamable HTTP endpoint (like Aliyun)

        Args:
            connection: Server connection
        """
        logger.info(f"Connecting to streamable server: {connection.config.url}")

        # Initialize connection with tools/list request
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list"
        }

        full_response = ""
        async with connection.client.stream('POST', connection.config.url, json=initialize_request) as response:
            logger.info(f"Response status: {response.status_code}")
            response.raise_for_status()

            # Parse streaming response
            tools = []
            async for chunk in response.aiter_bytes():
                # Parse JSON from chunk
                try:
                    if chunk:
                        text = chunk.decode('utf-8')
                        full_response += text
                        # Handle multiple JSON objects in response
                        for line in text.strip().split('\n'):
                            if line.strip():
                                logger.debug(f"Received chunk: {line[:200]}...")
                                result = json.loads(line)
                                if "result" in result and "tools" in result["result"]:
                                    tools = result["result"]["tools"]
                                    logger.info(f"Found {len(tools)} tools in response")
                except Exception as e:
                    logger.debug(f"Error parsing chunk: {e}")
                    continue

        logger.info(f"Full response received: {full_response[:500]}...")

        if tools:
            connection.tools = {tool["name"]: tool for tool in tools}
            connection.config.tool_count = len(connection.tools)
            connection.config.status = ConnectionStatus.CONNECTED
            connection.config.last_connected = datetime.utcnow()

            logger.info(
                f"Connected to streamable server {connection.config.name}, "
                f"loaded {len(connection.tools)} tools"
            )
        else:
            # If no tools found, still mark as connected
            connection.config.status = ConnectionStatus.CONNECTED
            connection.config.last_connected = datetime.utcnow()
            logger.info(f"Connected to streamable server {connection.config.name}")

    async def _call_server_tool(
        self,
        connection: MCPServerConnection,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: int
    ) -> Any:
        """Call tool on specific server

        Args:
            connection: Server connection
            tool_name: Tool name
            arguments: Tool arguments
            timeout: Request timeout

        Returns:
            Tool result
        """
        if not connection.client:
            raise ValueError("Server not connected")

        # For streamable servers, call directly to the URL with tools/call method
        if connection.config.server_type == "streamable":
            call_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            response = await connection.client.post(
                connection.config.url,
                json=call_request,
                timeout=timeout
            )
            response.raise_for_status()

            # Parse streaming response
            result = None
            async for chunk in response.aiter_bytes():
                if chunk:
                    text = chunk.decode('utf-8')
                    for line in text.strip().split('\n'):
                        if line.strip():
                            data = json.loads(line)
                            if "result" in data:
                                result = data["result"]
                            elif "error" in data:
                                raise ValueError(f"Tool error: {data['error']}")

            # Extract nested result if it's in content format
            if isinstance(result, dict) and "content" in result:
                content_list = result.get("content", [])
                if content_list and isinstance(content_list[0], dict):
                    text_content = content_list[0].get("text", "")
                    if text_content:
                        # Try to parse as JSON
                        try:
                            parsed = json.loads(text_content)
                            if "output" in parsed:
                                return parsed["output"]
                        except:
                            pass

            return result
        else:
            # Standard MCP server
            response = await connection.client.post(
                f"{connection.config.url}/tools/call",
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

    def _start_health_check(self, connection: MCPServerConnection):
        """Start health check for connection

        Args:
            connection: Server connection
        """
        async def health_check():
            while True:
                await asyncio.sleep(connection.health_check_interval)

                try:
                    # Simple health check
                    if connection.client:
                        try:
                            response = await connection.client.post(
                                f"{connection.config.url}/ping",
                                json={"jsonrpc": "2.0", "id": 1, "method": "ping"}
                            )
                            # Update status based on response
                            pass
                        except httpx.HTTPStatusError as e:
                            # If ping returns 404, the server might not support ping
                            # This is not necessarily a critical error
                            if e.response.status_code == 404:
                                logger.debug(f"Server {connection.config.name} does not support /ping endpoint")
                            else:
                                raise

                except Exception as e:
                    logger.warning(f"Health check failed for {connection.config.name}: {e}")
                    # Could trigger reconnect here

        connection.health_check_task = asyncio.create_task(health_check())

    async def close_all(self):
        """Close all connections"""
        async with self.lock:
            for server_id, connection in self.connections.items():
                if connection.health_check_task:
                    connection.health_check_task.cancel()

                if connection.client:
                    await connection.client.aclose()

            self.connections.clear()
            logger.info("Closed all MCP server connections")


# Global MCP client pool instance
mcp_client_pool = MCPClientPool()
