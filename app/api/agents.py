"""Agent management API endpoints"""
from fastapi import APIRouter, HTTPException
from typing import List, Optional
import logging

from app.models.agent import AgentCreate, AgentUpdate, AgentResponse
from app.services.agent_service import agent_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def list_agents(enabled_only: bool = False):
    """List all agents"""
    try:
        agents = await agent_service.list(enabled_only=enabled_only)
        return {"agents": agents}
    except Exception as e:
        logger.error(f"Error listing agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=AgentResponse)
async def create_agent(agent_data: AgentCreate):
    """Create a new agent"""
    try:
        agent = await agent_service.create(agent_data)
        return agent
    except Exception as e:
        logger.error(f"Error creating agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    """Get agent by ID"""
    try:
        agent = await agent_service.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: str, update_data: AgentUpdate):
    """Update agent"""
    try:
        agent = await agent_service.update(agent_id, update_data)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete agent"""
    try:
        success = await agent_service.delete(agent_id)
        if not success:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"success": True, "message": "Agent deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/select")
async def select_best_agent(request: dict):
    """Select best agent for current task"""
    try:
        message = request.get("message", "")
        conversation_history = request.get("conversation_history")

        if not message:
            raise HTTPException(status_code=400, detail="message is required")

        agent = await agent_service.select_best_agent(message, conversation_history)

        if not agent:
            return {
                "agent": None,
                "message": "No suitable agent found"
            }

        return {
            "agent": agent.dict(),
            "message": f"Selected agent: {agent.name}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error selecting agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))
