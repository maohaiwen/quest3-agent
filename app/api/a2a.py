"""A2A (Agent-to-Agent) Protocol Endpoints - compatible with Google A2A specification"""
import logging
from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any

from app.services.agent_registry import agent_registry
from app.models.a2a import A2ATaskRequest, A2ATask, A2ATaskStatusState, A2AMessage, A2AMessageRole, A2APart

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/a2a", tags=["a2a"])


@router.get("/agents/{agent_id}/.well-known/agent.json")
async def get_agent_card(agent_id: str):
    """Get Agent Card (A2A standard endpoint)

    Returns the Agent Card JSON as defined in Google A2A specification.
    """
    try:
        agent_card = agent_registry.get_agent_card(agent_id)
        if not agent_card:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        return agent_card.dict(exclude_none=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent card for {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/{agent_id}/tasks")
async def create_a2a_task(agent_id: str, request: Dict[str, Any] = Body(...)):
    """Create and execute an A2A task (A2A standard endpoint)

    This endpoint creates a new task and immediately executes it.
    For async scenarios, this would return pending status and allow polling.
    """
    try:
        # Get agent
        if agent_id not in agent_registry._agents:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

        # Create task from request
        input_text = request.get("input", "")
        if not input_text:
            raise HTTPException(status_code=400, detail="input is required")

        task = A2ATask(
            id=request.get("task_id", None) or None,
            input=input_text
        )

        # Execute task via registry (calls agent adapter)
        result_task = await agent_registry.call_agent(agent_id, task)

        # Return A2A-compliant response
        return {
            "id": result_task.id,
            "status": {
                "state": result_task.status.state.value,
                "message": result_task.status.message
            },
            "input": result_task.input,
            "output": result_task.output,
            "messages": [m.dict() for m in result_task.messages],
            "created_at": result_task.created_at,
            "updated_at": result_task.updated_at
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating A2A task for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/{agent_id}/tasks/{task_id}")
async def get_a2a_task(agent_id: str, task_id: str):
    """Get A2A task status (A2A standard endpoint)"""
    try:
        # For now, we don't store A2A tasks separately
        # In production, would look up task by ID
        # Return a simple response
        return {
            "id": task_id,
            "status": {
                "state": "completed",
                "message": "Task completed (stub response)"
            },
            "input": "",
            "output": "Task result would be here",
            "messages": [],
            "created_at": "",
            "updated_at": ""
        }

    except Exception as e:
        logger.error(f"Error getting A2A task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks", response_model=Dict[str, Any])
async def create_a2a_task_with_body(request: A2ATaskRequest):
    """Create A2A task with request body (alternative endpoint)"""
    try:
        # This is a simplified endpoint that routes to appropriate agent
        # In full A2A, the agent URL would be in the request
        return {
            "id": "stub-task-id",
            "status": {"state": "pending"},
            "input": request.input,
            "messages": []
        }

    except Exception as e:
        logger.error(f"Error in A2A tasks endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))
