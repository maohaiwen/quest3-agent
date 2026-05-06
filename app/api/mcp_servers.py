"""MCP servers management API endpoints"""
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import logging
import uuid

from app.services.mcp_pool import mcp_client_pool, MCPServerConfig
from app.database.connection import DatabaseConnection
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/servers", tags=["mcp_servers"])


@router.get("")
async def list_servers():
    """List all MCP servers"""
    try:
        # Get all servers from database
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            servers_from_db = await db.fetch_all("SELECT * FROM mcp_servers")

            # Get connected servers info
            connected_servers = await mcp_client_pool.get_all_servers()

            # Merge status from connected servers
            connected_map = {s['id']: s for s in connected_servers}

            for server in servers_from_db:
                server_id = server['id']
                if server_id in connected_map:
                    # Add status and tool count from connected server
                    server.update({
                        'status': connected_map[server_id].get('status', 'disconnected'),
                        'tool_count': connected_map[server_id].get('tool_count', 0)
                    })
                else:
                    server['status'] = 'disconnected'
                    server['tool_count'] = 0

            return {"servers": servers_from_db}
        finally:
            await db.disconnect()
    except Exception as e:
        logger.error(f"Error listing servers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def add_server(request: Dict[str, Any]):
    """Add MCP server"""
    try:
        name = request.get("name")
        url = request.get("url")
        description = request.get("description", "")
        priority = request.get("priority", 0)
        server_type = request.get("server_type", "standard")
        headers_raw = request.get("headers", "")
        auth_header = request.get("auth_header", "")

        if not name or not url:
            raise HTTPException(status_code=400, detail="name and url are required")

        # Parse headers
        headers = {}
        if headers_raw:
            try:
                for line in headers_raw.strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        headers[key.strip()] = value.strip()
            except Exception as e:
                logger.warning(f"Failed to parse headers: {e}")

        # Add auth header if provided
        if auth_header:
            # Clean up the auth_header - remove any quotes
            auth_header_clean = auth_header.strip()
            if auth_header_clean.startswith('"') and auth_header_clean.endswith('"'):
                auth_header_clean = auth_header_clean[1:-1]

            if ':' in auth_header_clean:
                key, value = auth_header_clean.split(':', 1)
                headers[key.strip()] = value.strip()
            else:
                headers["Authorization"] = auth_header_clean

        # Create server config
        config = MCPServerConfig(
            id=str(uuid.uuid4()),
            name=name,
            url=url,
            description=description,
            priority=priority,
            enabled=True,
            headers=headers,
            server_type=server_type
        )

        # Save to database first
        await _save_server_to_db(config)

        # Try to connect to server (non-blocking)
        try:
            success = await mcp_client_pool.add_server(config)
            if success:
                return {
                    "success": True,
                    "server_id": config.id,
                    "message": f"Server '{name}' added successfully and connected",
                    "connected": True
                }
            else:
                return {
                    "success": True,
                    "server_id": config.id,
                    "message": f"Server '{name}' added but connection failed. Connect manually.",
                    "connected": False
                }
        except Exception as e:
            # Server added but connection failed
            logger.warning(f"Server added but connection failed: {e}")
            return {
                "success": True,
                "server_id": config.id,
                "message": f"Server '{name}' added but connection failed. Connect manually.",
                "connected": False,
                "error": str(e)
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{server_id}")
async def get_server(server_id: str):
    """Get server by ID"""
    try:
        server = await mcp_client_pool.get_server(server_id)

        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        return server

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{server_id}")
async def delete_server(server_id: str):
    """Delete MCP server"""
    try:
        # First, remove from database
        await _delete_server_from_db(server_id)

        # Then try to remove from pool (may fail if not connected)
        await mcp_client_pool.remove_server(server_id)

        return {
            "success": True,
            "message": "Server deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{server_id}/connect")
async def connect_server(server_id: str):
    """Connect to MCP server"""
    try:
        # Get server from database to get config including server_type
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            server_data = await db.fetch_one(
                "SELECT * FROM mcp_servers WHERE id = ?",
                (server_id,)
            )

            if not server_data:
                raise HTTPException(status_code=404, detail="Server not found")

            # Remove from pool if exists
            await mcp_client_pool.remove_server(server_id)

            # Create server config
            config = MCPServerConfig(
                id=server_data['id'],
                name=server_data['name'],
                url=server_data['url'],
                description=server_data.get('description', ''),
                priority=server_data.get('priority', 0),
                enabled=bool(server_data.get('enabled', 1)),
                server_type=server_data.get('server_type', 'standard')
            )

            # Parse headers if stored
            import json
            headers = {}
            if server_data.get('headers'):
                try:
                    headers = json.loads(server_data['headers'])
                except:
                    pass

            config.headers = headers

            # Add server to pool and connect
            success = await mcp_client_pool.add_server(config)

            if success:
                return {
                    "success": True,
                    "message": "Connected to server"
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to connect to server"
                }
        finally:
            await db.disconnect()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error connecting to server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{server_id}/disconnect")
async def disconnect_server(server_id: str):
    """Disconnect from MCP server"""
    try:
        success = await mcp_client_pool.disconnect_server(server_id)

        if success:
            return {
                "success": True,
                "message": "Disconnected from server"
            }
        else:
            return {
                "success": False,
                "message": "Server not found or already disconnected"
            }

    except Exception as e:
        logger.error(f"Error disconnecting from server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools/catalog")
async def get_tools_catalog():
    """Get tool catalog from all connected servers.

    Returns a lightweight summary of all tools grouped by server,
    suitable for the Agent editor's tool selector UI.
    """
    try:
        # Get MCP remote tools from client pool
        mcp_tools = await mcp_client_pool.get_all_tools()

        # Get local tools from unified tool manager
        from app.core.tool_manager import get_tool_manager
        tool_manager = get_tool_manager()
        local_tools = await tool_manager.get_available_tools()

        # Merge all tools
        all_tools = {}

        # Add local tools first
        for tool_name, tool_def in local_tools.items():
            if tool_def.source == "local":
                all_tools[tool_name] = {
                    "name": tool_name,
                    "description": tool_def.description,
                    "original_name": tool_def.original_name or tool_name,
                    "server_id": "local",
                    "server_name": "本地工具",
                    "source": "local",
                }
            elif tool_def.source == "skill":
                all_tools[tool_name] = {
                    "name": tool_name,
                    "description": tool_def.description,
                    "original_name": tool_def.original_name or tool_name,
                    "server_id": "skill",
                    "server_name": "技能工具",
                    "source": "skill",
                }

        # Add MCP remote tools
        for tool_name, tool_info in mcp_tools.items():
            if tool_info.get("source") == "local":
                # Skip local tools already added above from unified tool manager
                continue
            all_tools[tool_name] = tool_info

        # Group by server_id
        servers_map: Dict[str, Any] = {}
        for tool_name, tool_info in all_tools.items():
            source = tool_info.get("source", "unknown")
            server_id = tool_info.get("server_id", "local")
            server_name = tool_info.get("server_name", "本地")

            if source == "local":
                server_id = "local"
                server_name = "本地工具"
            elif source == "skill":
                server_id = "skill"
                server_name = "技能工具"

            if server_id not in servers_map:
                servers_map[server_id] = {
                    "server_id": server_id,
                    "server_name": server_name,
                    "tools": []
                }

            servers_map[server_id]["tools"].append({
                "name": tool_name,
                "description": tool_info.get("description", ""),
                "original_name": tool_info.get("original_name", tool_name),
            })

        return {
            "servers": list(servers_map.values()),
            "total_tools": len(all_tools)
        }
    except Exception as e:
        logger.error(f"Error getting tools catalog: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tools/recommend")
async def recommend_tools(request: Dict[str, Any]):
    """Use AI to recommend tools based on user's requirement description.

    Request body:
        requirement: Natural language description of what the user needs
    Response:
        recommended_tools: List of tool names that match the requirement
    """
    try:
        requirement = request.get("requirement", "").strip()
        if not requirement:
            raise HTTPException(status_code=400, detail="requirement is required")

        # Get all available tools
        all_tools = await mcp_client_pool.get_all_tools()
        if not all_tools:
            return {"recommended_tools": []}

        # Build tool list for prompt
        tool_lines = []
        valid_tool_names = set()
        for tool_name, tool_info in all_tools.items():
            source = tool_info.get("source", "unknown")
            if source == "local":
                continue  # Skip local/skill tools
            desc = tool_info.get("description", "").strip()
            tool_lines.append(f"- {tool_name}: {desc}")
            valid_tool_names.add(tool_name)

        if not tool_lines:
            return {"recommended_tools": []}

        tools_text = "\n".join(tool_lines)

        # Build prompt
        prompt = f"""你是一个工具选择助手。根据用户的需求，从以下工具列表中选择最合适的工具。

用户需求：{requirement}

可用工具：
{tools_text}

请只返回一个JSON数组，包含你推荐的工具名称，不要返回其他内容。
示例：["tool_name_1", "tool_name_3"]"""

        # Call LLM
        from app.services.llm_service import llm_service

        if not llm_service.is_configured():
            raise HTTPException(status_code=500, detail="LLM service not configured. Please set VOLCENGINE_API_KEY.")

        messages = [{"role": "user", "content": prompt}]
        response_text = await llm_service._chat_completion(
            messages=messages,
            temperature=0.1,
            max_tokens=2000
        )

        # Parse LLM response as JSON array
        import json
        import re

        # Try to extract JSON array from response (handle markdown code blocks)
        json_match = re.search(r'\[.*?\]', response_text, re.DOTALL)
        if not json_match:
            logger.warning(f"LLM response is not a valid JSON array: {response_text[:200]}")
            return {"recommended_tools": []}

        try:
            recommended = json.loads(json_match.group())
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON: {json_match.group()[:200]}")
            return {"recommended_tools": []}

        # Validate tool names against catalog
        validated = [name for name in recommended if isinstance(name, str) and name in valid_tool_names]

        logger.info(f"AI recommended {len(validated)} tools for requirement: {requirement[:50]}")
        return {"recommended_tools": validated}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error recommending tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{server_id}/test")
async def test_server_connection(server_id: str):
    """Test server connection"""
    try:
        result = await mcp_client_pool.test_connection(server_id)
        return result

    except Exception as e:
        logger.error(f"Error testing server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{server_id}/tools")
async def get_server_tools(server_id: str):
    """Get tools from specific server"""
    try:
        # Get server connection
        server = await mcp_client_pool.get_server(server_id)

        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        # Get tools from this server
        connection = mcp_client_pool.connections.get(server_id)

        if not connection or not connection.tools:
            return {
                "server_id": server_id,
                "tools": []
            }

        tools = [
            {
                "name": tool_name,
                "description": tool.get("description", ""),
                "input_schema": tool.get("inputSchema", {})
            }
            for tool_name, tool in connection.tools.items()
        ]

        return {
            "server_id": server_id,
            "tools": tools
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting server tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{server_id}/tools/call")
async def call_server_tool(server_id: str, request: Dict[str, Any]):
    """Call a tool on specific MCP server"""
    try:
        tool_name = request.get("tool_name")
        arguments = request.get("arguments", {})

        if not tool_name:
            raise HTTPException(status_code=400, detail="tool_name is required")

        # Get connection
        connection = mcp_client_pool.connections.get(server_id)
        if not connection:
            raise HTTPException(status_code=404, detail="Server not connected")

        # Check if tool exists
        if tool_name not in connection.tools:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

        # Call tool directly on connection
        result = await mcp_client_pool._call_server_tool(
            connection,
            tool_name,
            arguments,
            timeout=60
        )

        return {
            "success": True,
            "tool_name": tool_name,
            "result": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calling tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _save_server_to_db(config: MCPServerConfig):
    """Save server configuration to database

    Args:
        config: Server configuration
    """
    db = DatabaseConnection(settings.DATABASE_URL)
    await db.connect()

    try:
        # Serialize headers to JSON
        import json
        headers_json = json.dumps(config.headers) if config.headers else "{}"

        await db.execute("""
        INSERT INTO mcp_servers (id, name, url, description, priority, enabled, added_at, headers, server_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            config.id,
            config.name,
            config.url,
            config.description,
            config.priority,
            1 if config.enabled else 0,
            config.added_at.isoformat(),
            headers_json,
            config.server_type
        ))
        await db.commit()

    finally:
        await db.disconnect()


async def _delete_server_from_db(server_id: str):
    """Delete server from database

    Args:
        server_id: Server ID
    """
    db = DatabaseConnection(settings.DATABASE_URL)
    await db.connect()

    try:
        await db.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
        await db.commit()

    finally:
        await db.disconnect()
