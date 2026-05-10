"""Sandbox internal API - allows sandbox subprocess to call tools via HTTP.

This endpoint is only accessible with a valid sandbox token (generated per execution).
The sandbox code uses call_tool() which hits this endpoint internally.

Tool access is scoped by the token's allowed_tools — the sandbox can only
call tools that the invoking agent has access to.
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

from app.tools.sandbox_bridge import validate_token, get_token_allowed_tools
from app.core.tool_manager import get_tool_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


class ToolCallRequest(BaseModel):
    """Request body for sandbox tool call"""
    tool_name: str
    arguments: Dict[str, Any] = {}
    token: str


class ToolListRequest(BaseModel):
    """Request body for sandbox tool listing"""
    token: str


def _check_tool_allowed(token: str, tool_name: str) -> bool:
    """Check if a tool is allowed by the token's whitelist."""
    allowed = get_token_allowed_tools(token)
    if allowed is None:
        # None = all tools allowed
        return True
    return tool_name in allowed


@router.post("/call-tool")
async def sandbox_call_tool(request: ToolCallRequest):
    """Internal endpoint for sandbox to call tools.

    Requires a valid sandbox token. Tool access is scoped by the token's
    allowed_tools list (inherited from the agent's tool configuration).
    """
    if not validate_token(request.token):
        raise HTTPException(status_code=403, detail="Invalid or expired sandbox token")

    if not _check_tool_allowed(request.token, request.tool_name):
        return {
            "success": False,
            "error": f"Tool '{request.tool_name}' is not available in this sandbox session"
        }

    tool_manager = get_tool_manager()

    try:
        result = await tool_manager.call_tool(request.tool_name, request.arguments)
        # Ensure result is JSON-serializable
        if isinstance(result, dict):
            return {"success": True, "result": result}
        elif isinstance(result, str):
            return {"success": True, "result": result}
        elif isinstance(result, list):
            return {"success": True, "result": result}
        else:
            return {"success": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Sandbox tool call error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/list-tools")
async def sandbox_list_tools(request: ToolListRequest):
    """Internal endpoint for sandbox to list available tools.

    Only returns tools that are in the token's allowed_tools whitelist.
    """
    if not validate_token(request.token):
        raise HTTPException(status_code=403, detail="Invalid or expired sandbox token")

    allowed = get_token_allowed_tools(request.token)
    tool_manager = get_tool_manager()
    tools = await tool_manager.get_available_tools()

    tool_list = []
    for name, tool_def in tools.items():
        # Filter by allowed_tools whitelist
        if allowed is not None and name not in allowed:
            continue
        tool_list.append({
            "name": name,
            "description": tool_def.description,
            "input_schema": tool_def.input_schema,
        })

    return {"success": True, "tools": tool_list}
