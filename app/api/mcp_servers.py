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
