
"""MCP tools management API endpoints"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any
import logging

from app.services.mcp_service import mcp_tool_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/tools")
async def list_tools():
    """List all available MCP tools"""
    try:
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
            "mcp_server_url": mcp_tool_manager.mcp_service.server_url,
            "total_tools": len(mcp_tool_manager.all_tools),
            "tools": all_tools,
            "tools_description": tools
        }
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools/{tool_name}")
async def get_tool(tool_name: str):
    """Get specific tool information"""
    tool = mcp_tool_manager.mcp_service.get_tool(tool_name)

    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema
    }


@router.post("/call")
async def call_tool(request: Dict[str, Any]):
    """Call a tool"""
    try:
        tool_name = request.get("tool_name")
        arguments = request.get("arguments", {})

        if not tool_name:
            raise HTTPException(status_code=400, detail="tool_name is required")

        result = await mcp_tool_manager.call_tool(tool_name, arguments)

        return {
            "tool_name": tool_name,
            "result": result,
            "success": True
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error calling tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connect")
async def connect_mcp_server(request: Dict[str, Any]):
    """Connect to an MCP server"""
    try:
        server_url = request.get("server_url")

        if not server_url:
            raise HTTPException(status_code=400, detail="server_url is required")

        # Disconnect existing connection if any
        if mcp_tool_manager.mcp_service.is_connected():
            await mcp_tool_manager.mcp_service.disconnect()

        # Connect to new server
        success = await mcp_tool_manager.connect_to_mcp_server(server_url)

        if success:
            return {
                "success": True,
                "message": f"Connected to MCP server: {server_url}",
                "tools_count": len(mcp_tool_manager.mcp_service.tools)
            }
        else:
            return {
                "success": False,
                "message": f"Failed to connect to MCP server: {server_url}"
            }

    except Exception as e:
        logger.error(f"Error connecting to MCP server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnect")
async def disconnect_mcp_server():
    """Disconnect from MCP server"""
    try:
        if not mcp_tool_manager.mcp_service.is_connected():
            return {
                "success": True,
                "message": "No active MCP connection"
            }

        await mcp_tool_manager.mcp_service.disconnect()

        return {
            "success": True,
            "message": "Disconnected from MCP server"
        }
    except Exception as e:
        logger.error(f"Error disconnecting from MCP server: {e}")
        raise HTTPException(status_code=500, detail=str(e))
