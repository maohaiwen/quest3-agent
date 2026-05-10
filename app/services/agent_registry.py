"""Agent Registry - manages process-internal Agent instances and A2A-compliant calling"""
import logging
import httpx
from typing import Dict, Optional, List
from app.models.a2a import A2ATask, AgentCard
from app.models.agent import AgentResponse

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry for process-internal Agent instances with A2A-compliant calling.

    Designed to be non-intrusive: does not modify existing Agent code.
    Uses A2AAdapter to wrap existing Agents into A2A-compatible form.
    """

    def __init__(self):
        self._agents: Dict[str, "A2AAdapter"] = {}
        self._agent_cards: Dict[str, AgentCard] = {}

    async def initialize(self):
        """Initialize registry by loading existing agents from database"""
        try:
            from app.services.agent_service import agent_service
            agents = await agent_service.list(enabled_only=True)
            for agent in agents:
                await self.register_existing_agent(agent)
            logger.info(f"Agent registry initialized with {len(self._agents)} agents")
        except Exception as e:
            logger.warning(f"Failed to initialize agent registry: {e}")

    async def register_existing_agent(self, agent: AgentResponse) -> None:
        """Register an existing Agent (from database) with A2A adapter wrapper"""
        from app.services.a2a_adapter import A2AAdapter
        adapter = A2AAdapter(agent)
        self._agents[agent.id] = adapter
        self._agent_cards[agent.id] = await adapter.get_agent_card()
        logger.info(f"Registered existing agent: {agent.name} (id={agent.id})")

    def register_adapter(self, agent_id: str, adapter: "A2AAdapter") -> None:
        """Register an A2A adapter directly"""
        self._agents[agent_id] = adapter
        self._agent_cards[agent_id] = adapter.get_agent_card_sync()

    def unregister(self, agent_id: str) -> None:
        """Unregister an agent"""
        self._agents.pop(agent_id, None)
        self._agent_cards.pop(agent_id, None)

    def get_agent_card(self, agent_id: str) -> Optional[AgentCard]:
        """Get Agent Card for a registered agent"""
        return self._agent_cards.get(agent_id)

    def list_agent_cards(self) -> List[AgentCard]:
        """List all registered Agent Cards"""
        return list(self._agent_cards.values())

    async def call_agent(self, agent_id: str, task: A2ATask) -> A2ATask:
        """Call an agent with A2A task.

        For local agents: direct in-process method call via adapter.
        For remote agents: HTTP call to their A2A endpoint.
        """
        # Check if it's a local agent
        if agent_id in self._agents:
            logger.info(f"Calling local agent {agent_id} with task {task.id}")
            return await self._agents[agent_id].handle_task(task)

        # For remote agents, try to find by URL in agent cards
        # First check if any registered agent has a remote URL matching
        logger.info(f"Agent {agent_id} not in local registry, attempting remote call")

        # Try to construct remote URL or use agent_card url
        # For now, assume agent_id might be a URL or we need to look up
        raise ValueError(f"Agent {agent_id} not found in registry and remote call not configured")

    async def call_agent_stream(self, agent_id: str, task: A2ATask):
        """Call an agent with streaming events (thinking, tool calls, observations).

        Yields dicts: {"type": "thinking"|"action"|"observation"|"content"|"phase"|"error", ...}
        The caller should add agent_id before forwarding to SSE.
        """
        if agent_id not in self._agents:
            raise ValueError(f"Agent {agent_id} not found in registry")

        logger.info(f"Streaming agent {agent_id} with task {task.id}")
        event_count = 0
        async for event in self._agents[agent_id].handle_task_stream(task):
            event_count += 1
            if event_count <= 3 or event_count % 20 == 0:
                logger.debug(f"Stream event #{event_count} from agent {agent_id}: type={event.get('type')}")
            yield event
        logger.info(f"Streaming agent {agent_id} done, {event_count} events total")

    async def call_remote_agent(self, agent_card: AgentCard, task: A2ATask) -> A2ATask:
        """Call a remote agent via HTTP (A2A protocol)"""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Create task via POST /a2a/tasks
                response = await client.post(
                    f"{agent_card.url}/tasks",
                    json={
                        "input": task.input,
                        "task_id": task.id,
                    }
                )
                response.raise_for_status()
                result = response.json()

                # Return updated task
                task.output = result.get("output", "")
                task.status.state = result.get("status", {}).get("state", "completed")
                return task
        except Exception as e:
            logger.error(f"Remote agent call failed: {e}")
            task.status.state = "failed"
            task.status.message = str(e)
            return task


# Global agent registry instance
agent_registry = AgentRegistry()
