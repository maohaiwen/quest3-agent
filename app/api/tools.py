"""Tool management API endpoints — list tools with status, install deps"""
import logging
from fastapi import APIRouter, HTTPException
from typing import Optional

from app.core.tool_manager import get_tool_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools():
    """List all tool plugins with install status, grouped by service.

    Returns each service with:
    - service_name, installed, deps, tools[]
    - For each tool: name, description, installed
    """
    tool_manager = get_tool_manager()
    plugins = tool_manager.get_tool_plugins()
    return {"plugins": plugins}


@router.post("/{service_name}/install")
async def install_service(service_name: str):
    """Install pip dependencies for a tool service.

    Triggers `pip install` in the background and returns status.
    Check progress with GET /api/tools/{service_name}/install-status.
    """
    tool_manager = get_tool_manager()

    # Check service exists
    from app.tools.plugin_registry import get_service_descriptors
    descriptors = get_service_descriptors()
    if service_name not in descriptors:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

    desc = descriptors[service_name]
    if not desc.service_cls.deps:
        raise HTTPException(status_code=400, detail=f"Service '{service_name}' has no dependencies to install")

    # Check if already installed
    if desc.service_cls.is_installed():
        return {"success": True, "message": "Already installed", "status": "installed"}

    # Start installation
    result = await tool_manager.install_service_deps(service_name)
    return result


@router.get("/{service_name}/install-status")
async def get_install_status(service_name: str):
    """Get the current installation status for a service.

    Returns:
        status: "not_started" | "installing" | "installed" | "failed"
        output: Last 500 chars of pip output
        error: Error message if failed
    """
    tool_manager = get_tool_manager()
    status = tool_manager.get_install_status(service_name)

    if not status:
        # Check if it's actually already installed
        from app.tools.plugin_registry import get_service_descriptors
        descriptors = get_service_descriptors()
        if service_name in descriptors and descriptors[service_name].service_cls.is_installed():
            return {"status": "installed", "output": "", "error": ""}
        return {"status": "not_started", "output": "", "error": ""}

    return status


@router.post("/{service_name}/check-deps")
async def check_service_deps(service_name: str):
    """Check dependency status for a service.

    Returns which deps are installed and which are missing.
    """
    from app.tools.plugin_registry import get_service_descriptors
    descriptors = get_service_descriptors()
    if service_name not in descriptors:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")

    desc = descriptors[service_name]
    dep_status = desc.service_cls.check_deps()

    return {
        "service_name": service_name,
        "deps": dep_status,
        "all_installed": all(dep_status.values()) if dep_status else True,
    }
