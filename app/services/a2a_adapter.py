"""A2A Adapter - wraps existing Agents into A2A-compliant form without modifying Agent code"""
import logging
from typing import Optional, List, Dict, Any
from app.models.a2a import A2ATask, A2AMessage, A2AMessageRole, A2APart, A2APartType, AgentCard
from app.models.agent import AgentResponse
from app.services.llm_service import llm_service
from app.config import settings

logger = logging.getLogger(__name__)


class A2AAdapter:
    """Adapts an existing Agent to A2A protocol without modifying Agent code.

    This is a non-intrusive wrapper that:
    1. Reads Agent configuration (system_prompt, model, execution_mode, etc.)
    2. Calls existing execution functions directly (no HTTP overhead)
    3. Converts results to A2A Task format
    """

    def __init__(self, agent: AgentResponse):
        self.agent_id = agent.id
        self.agent = agent
        self._llm_service = llm_service

    async def get_agent_card(self) -> AgentCard:
        """Return Agent Card exposed at /.well-known/agent.json"""
        return AgentCard(
            name=self.agent.name,
            description=self.agent.description,
            url=f"/a2a/agents/{self.agent.id}/tasks",
            version="1.0.0",
            capabilities=self.agent.skills + self.agent.tools,
            agent_id=self.agent.id,
        )

    def get_agent_card_sync(self) -> AgentCard:
        """Synchronous version of get_agent_card"""
        return AgentCard(
            name=self.agent.name,
            description=self.agent.description,
            url=f"/a2a/agents/{self.agent.id}/tasks",
            version="1.0.0",
            capabilities=self.agent.skills + self.agent.tools,
            agent_id=self.agent.id,
        )

    def _build_agent_config_dict(self) -> Dict[str, Any]:
        """Build agent config dict for execution engines (same format as chat.py uses)"""
        # Build skill system prompt addition
        skill_prompt = ""
        if hasattr(self.agent, 'skills') and self.agent.skills:
            try:
                from app.skills.registry import get_skill_registry
                registry = get_skill_registry()
                skill_prompt = registry.get_system_prompt_addition(self.agent_id)
            except Exception as e:
                logger.warning(f"Failed to get skill prompt: {e}")

        system_prompt = self.agent.system_prompt or ""
        if skill_prompt:
            system_prompt = (system_prompt + "\n" + skill_prompt) if system_prompt else skill_prompt

        return {
            "name": self.agent.name,
            "system_prompt": system_prompt,
            "model": self.agent.model,
            "temperature": self.agent.temperature,
            "max_tokens": self.agent.max_tokens,
            "tools": self.agent.tools if hasattr(self.agent, 'tools') else [],
            "mcp_servers": self.agent.mcp_servers if hasattr(self.agent, 'mcp_servers') else [],
            "thinking_effort": getattr(self.agent, 'thinking_effort', 'medium'),
            "max_react_steps": getattr(self.agent, 'max_react_steps', 15),
        }

    async def handle_task(self, task: A2ATask) -> A2ATask:
        """Handle an A2A task by calling the appropriate execution engine.

        Routes to the correct execution mode (direct, plan, react, react_cot)
        matching the behavior of the chat API.
        """
        try:
            logger.info(f"Agent {self.agent.name} handling task {task.id}: {task.input[:50]}...")

            execution_mode = getattr(self.agent, 'execution_mode', 'direct')
            agent_config_dict = self._build_agent_config_dict()

            full_response = ""

            if execution_mode == "react_cot":
                full_response = await self._execute_react_cot(task.input, agent_config_dict)
            elif execution_mode in ("plan", "react"):
                full_response = await self._execute_planning(task.input, agent_config_dict, execution_mode)
            else:
                # direct mode - simple LLM call
                full_response = await self._execute_direct(task.input, agent_config_dict)

            # Update task with result
            task.set_completed(full_response)
            task.add_message(A2AMessageRole.AGENT, full_response)

            logger.info(f"Task {task.id} completed, response length: {len(full_response)}")
            return task

        except Exception as e:
            logger.error(f"Error handling task {task.id}: {e}", exc_info=True)
            task.set_failed(str(e))
            return task

    async def _execute_direct(self, task_input: str, agent_config: Dict[str, Any]) -> str:
        """Direct LLM call (no planning, no tools)"""
        messages = []
        system_prompt = agent_config.get("system_prompt", "")
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task_input})

        model = agent_config.get("model") or settings.VOLCENGINE_MODEL
        temperature = agent_config.get("temperature") if agent_config.get("temperature") is not None else settings.LLM_TEMPERATURE
        max_tokens = agent_config.get("max_tokens") or settings.LLM_MAX_TOKENS

        return await self._llm_service._chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _execute_react_cot(self, task_input: str, agent_config: Dict[str, Any]) -> str:
        """ReAct + Chain of Thought execution mode"""
        from app.core.react_cot_executor import ReActCotExecutor

        executor = ReActCotExecutor(agent_config=agent_config)
        full_response = ""

        async for event in executor.execute(
            task_input,
            conversation_history=None,
            deep_thinking=True
        ):
            if event.get("type") == "cot_complete":
                full_response = event.get("message", "")

        return full_response or ""

    async def _execute_planning(self, task_input: str, agent_config: Dict[str, Any], execution_mode: str) -> str:
        """Plan or React execution mode

        Uses ReActCotExecutor which supports Volcengine LLM + tools,
        since planning_chat_service depends on Anthropic SDK which may not be configured.
        """
        # Use ReActCotExecutor for both react and plan modes
        # It supports tool calling, thinking, and works with Volcengine
        from app.core.react_cot_executor import ReActCotExecutor

        executor = ReActCotExecutor(agent_config=agent_config)
        full_response = ""

        async for event in executor.execute(
            task_input,
            conversation_history=None,
            deep_thinking=True
        ):
            if event.get("type") == "cot_complete":
                full_response = event.get("message", "")

        return full_response or ""
