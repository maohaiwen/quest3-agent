"""A2A Adapter - wraps existing Agents into A2A-compliant form without modifying Agent code"""
import json
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
        """Build agent config dict for execution engines"""
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
        """Handle an A2A task by calling the appropriate execution engine."""
        try:
            logger.info(f"Agent {self.agent.name} handling task {task.id}: {task.input[:50]}...")

            execution_mode = getattr(self.agent, 'execution_mode', 'direct')
            # Backward compat: react_cot maps to react
            if execution_mode == "react_cot":
                execution_mode = "react"
            agent_config_dict = self._build_agent_config_dict()

            if execution_mode == "direct":
                full_response = await self._execute_direct(task.input, agent_config_dict)
            else:
                # plan and react both use ReActCotExecutor
                full_response = await self._execute_react(task.input, agent_config_dict)

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

        model = agent_config.get("model") or self._llm_service.model
        temperature = agent_config.get("temperature") if agent_config.get("temperature") is not None else settings.LLM_TEMPERATURE
        max_tokens = agent_config.get("max_tokens") or settings.LLM_MAX_TOKENS

        return await self._llm_service._chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _execute_react(self, task_input: str, agent_config: Dict[str, Any]) -> str:
        """ReAct execution mode (used for plan and react modes)"""
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

    # ------------------------------------------------------------------
    # Streaming execution — yields intermediate events for real-time UI
    # ------------------------------------------------------------------

    async def handle_task_stream(self, task: A2ATask):
        """Stream agent execution events (thinking, tool calls, observations).

        Yields dicts with type + payload.  The caller (collaboration modes)
        can forward these through the SSE channel after adding agent_id.
        """
        try:
            execution_mode = getattr(self.agent, 'execution_mode', 'direct')
            if execution_mode == "react_cot":
                execution_mode = "react"
            logger.info(f"Agent {self.agent.name} streaming task {task.id} (mode={execution_mode})")

            # Yield an immediate "phase: thinking" so the UI shows activity
            # before the LLM produces any output
            yield {"type": "phase", "phase": "thinking"}

            agent_config_dict = self._build_agent_config_dict()

            event_count = 0
            if execution_mode == "direct":
                async for event in self._execute_direct_stream(
                    task, task.input, agent_config_dict
                ):
                    event_count += 1
                    yield event
            else:
                async for event in self._execute_react_stream(
                    task, task.input, agent_config_dict
                ):
                    event_count += 1
                    yield event

            logger.info(f"Agent {self.agent.name} task {task.id} streaming done, {event_count} events yielded")

        except Exception as e:
            logger.error(f"Error streaming task {task.id}: {e}", exc_info=True)
            yield {"type": "error", "message": str(e)}
            task.set_failed(str(e))

    async def _execute_direct_stream(
        self, task: A2ATask, task_input: str, agent_config: Dict[str, Any]
    ):
        """Stream a direct LLM call, yielding content chunks."""
        messages = []
        system_prompt = agent_config.get("system_prompt", "")
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": task_input})

        model = agent_config.get("model") or self._llm_service.model
        temperature = agent_config.get("temperature") if agent_config.get("temperature") is not None else settings.LLM_TEMPERATURE
        max_tokens = agent_config.get("max_tokens") or settings.LLM_MAX_TOKENS

        full_response = ""
        logger.info(f"Direct stream starting for task {task.id}, model={model}")
        chunk_count = 0
        async for content, thinking in self._llm_service._chat_completion_stream_with_thinking(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=True,
        ):
            chunk_count += 1
            if thinking:
                yield {"type": "thinking", "content": thinking}
            if content:
                full_response += content
                yield {"type": "content", "content": content}

        logger.info(f"Direct stream done for task {task.id}, {chunk_count} chunks, response len={len(full_response)}")
        task.set_completed(full_response)
        task.add_message(A2AMessageRole.AGENT, full_response)

    async def _execute_react_stream(
        self, task: A2ATask, task_input: str, agent_config: Dict[str, Any]
    ):
        """Stream ReAct execution, yielding thinking / tool / content events."""
        from app.core.react_cot_executor import ReActCotExecutor

        # Pass sandbox tools/handler from A2ATask to executor config
        if task.sandbox_tools:
            agent_config = dict(agent_config)  # copy to avoid mutation
            agent_config["sandbox_tools"] = task.sandbox_tools
            agent_config["sandbox_handler"] = task.sandbox_handler

        executor = ReActCotExecutor(agent_config=agent_config)
        full_response = ""
        event_count = 0

        logger.info(f"ReAct stream starting for task {task.id}")
        async for event in executor.execute(
            task_input, conversation_history=None, deep_thinking=True
        ):
            evt_type = event.get("type")

            if evt_type == "cot_thinking":
                event_count += 1
                yield {
                    "type": "thinking",
                    "content": event["content"],
                    "step": event.get("step", 1),
                }

            elif evt_type == "cot_phase":
                event_count += 1
                yield {"type": "phase", "phase": event["phase"]}

            elif evt_type == "cot_action":
                event_count += 1
                yield {
                    "type": "action",
                    "tool_name": event["tool_name"],
                    "tool_args": event.get("tool_args", {}),
                }

            elif evt_type == "cot_observation":
                event_count += 1
                result = event["result"]
                # Truncate large results for SSE stream
                if isinstance(result, dict):
                    result_str = json.dumps(result, ensure_ascii=False)
                else:
                    result_str = str(result)
                if len(result_str) > 2000:
                    result_str = result_str[:2000] + "...(已截断)"
                yield {"type": "observation", "result": result_str}

            elif evt_type == "message":
                event_count += 1
                full_response += event["content"]
                yield {"type": "content", "content": event["content"]}

            elif evt_type == "cot_complete":
                full_response = event.get("message", full_response)

            elif evt_type == "error":
                event_count += 1
                yield {"type": "error", "message": event.get("message", "")}

        logger.info(f"ReAct stream done for task {task.id}, {event_count} events, response len={len(full_response)}")
        task.set_completed(full_response or "")
        task.add_message(A2AMessageRole.AGENT, full_response or "")
