"""Intelligent chat service with planning and execution capabilities"""
import logging
import json
from typing import Optional, AsyncGenerator, List, Dict, Any
from datetime import datetime

from app.config import settings
from app.core.decision import decision_engine
from app.core.execution import execution_engine, ExecutionStep, ExecutionPlan, ExecutionStrategy

logger = logging.getLogger(__name__)


class ChatEvent:
    """Chat event types for streaming"""

    @staticmethod
    def thinking(message: str) -> dict:
        """Thinking event"""
        return {
            "type": "thinking",
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        }

    @staticmethod
    def planning(plan: dict) -> dict:
        """Planning event"""
        return {
            "type": "planning",
            "plan": plan,
            "timestamp": datetime.utcnow().isoformat()
        }

    @staticmethod
    def step_start(step: dict) -> dict:
        """Step start event"""
        return {
            "type": "step_start",
            "step": step,
            "timestamp": datetime.utcnow().isoformat()
        }

    @staticmethod
    def step_progress(step_id: str, message: str) -> dict:
        """Step progress event"""
        return {
            "type": "step_progress",
            "step_id": step_id,
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        }

    @staticmethod
    def step_complete(step_id: str, result: Any) -> dict:
        """Step complete event"""
        # Truncate large results
        result_preview = result
        if isinstance(result, (dict, list)):
            result_str = json.dumps(result, ensure_ascii=False)
            if len(result_str) > 500:
                result_preview = json.dumps(result, ensure_ascii=False)[:500] + "..."
        elif isinstance(result, str) and len(result) > 500:
            result_preview = result[:500] + "..."

        return {
            "type": "step_complete",
            "step_id": step_id,
            "result": result_preview,
            "timestamp": datetime.utcnow().isoformat()
        }

    @staticmethod
    def step_error(step_id: str, error: str) -> dict:
        """Step error event"""
        return {
            "type": "step_error",
            "step_id": step_id,
            "error": error,
            "timestamp": datetime.utcnow().isoformat()
        }

    @staticmethod
    def message(content: str) -> dict:
        """Message event"""
        return {
            "type": "message",
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        }

    @staticmethod
    def done() -> dict:
        """Done event"""
        return {
            "type": "done",
            "timestamp": datetime.utcnow().isoformat()
        }


class PlanningChatService:
    """Chat service with planning and execution capabilities"""

    def __init__(self):
        """Initialize service"""
        self.model = settings.VOLCENGINE_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        self._llm_service = None

    def set_llm_service(self, llm_service):
        """Set LLM service instance

        Args:
            llm_service: LLMService instance
        """
        self._llm_service = llm_service

    @property
    def llm(self):
        """Get LLM service (lazy init)"""
        if self._llm_service is None:
            from app.services.llm_service import llm_service
            self._llm_service = llm_service
        return self._llm_service

    async def chat(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
        enable_planning: bool = True,
        use_react: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        deep_thinking: bool = False
    ) -> AsyncGenerator[dict, None]:
        """Chat with planning and execution capabilities - optimized for Plan mode

        Args:
            message: User message
            conversation_history: Conversation history
            enable_planning: Enable planning mode (for "plan" mode)
            use_react: Use ReAct executor (for "react" mode)
            agent_config: Agent configuration including tools
            deep_thinking: Enable deep thinking mode

        Yields:
            Chat events
        """
        if not self.llm.is_configured():
            yield ChatEvent.message("LLM not configured. Please set VOLCENGINE_API_KEY.")
            yield ChatEvent.done()
            return

        # Use ReAct executor for react mode (legacy path, react now handled directly in chat.py)
        if use_react:
            from app.core.react_cot_executor import ReActCotExecutor

            # Merge agent config with service config
            merged_config = {
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if agent_config:
                merged_config.update(agent_config)

            executor = ReActCotExecutor(
                agent_config=merged_config,
            )

            final_response = ""
            has_message = False

            async for event in executor.execute(
                task=message,
                conversation_history=conversation_history,
                deep_thinking=deep_thinking
            ):
                event_type = event.get("type")

                # Collect final message from complete event
                if event_type == "complete":
                    import time
                    start_time = time.time()
                    final_response = event.get("message", "任务已完成")
                    logger.info(f"PlanningChat: Got complete event, msg length: {len(final_response)}")
                    has_message = True
                    # Forward complete event directly, don't convert to ChatEvent.message
                    yield {
                        "type": "complete",
                        "message": final_response,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    logger.info(f"PlanningChat: complete event yielded after {(time.time() - start_time) * 1000:.2f}ms")

                # Map ReAct events to ChatEvent format
                elif event_type == "thinking":
                    if "content" not in event:
                        yield ChatEvent.thinking(event.get("message", ""))
                    else:
                        yield ChatEvent.thinking(event.get("content", ""))

                elif event_type == "action_start":
                    # Forward action_start event directly with arguments
                    step_id = f"step_{event.get('step', 1)}"
                    tool_name = event.get("tool_name", "")
                    arguments = event.get("arguments", {})
                    query = arguments.get("query", "") if isinstance(arguments, dict) else ""

                    yield {
                        "type": "action_start",
                        "step": event.get("step", 1),
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "thought": event.get("thought", ""),
                        "query": query  # Include query at top level for easier access
                    }

                    # Show search query in progress
                    if query:
                        yield ChatEvent.step_progress(
                            step_id,
                            f"🔍 正在搜索: {query}"
                        )
                    else:
                        yield ChatEvent.step_progress(
                            step_id,
                            f"调用工具: {tool_name}..."
                        )

                elif event_type == "observation":
                    # Forward observation event directly with step info
                    yield {
                        "type": "observation",
                        "step": event.get("step", 1),
                        "result": event.get("result", "")
                    }

                elif event_type == "error":
                    yield ChatEvent.step_error(
                        f"step_{event.get('step', 'unknown')}",
                        event.get("error", str(event))
                    )

                elif event_type == "terminated":
                    yield ChatEvent.message(f"任务终止: {event.get('reason', '未知原因')}")

                elif event_type == "incomplete":
                    # Generate final response from execution history
                    if not has_message:
                        results_summary = "\n\n".join([
                            f"步骤 {record.step}: {record.observation[:200]}"
                            for record in executor.execution_history
                        ])
                        final_msg = f"任务未完全完成。已执行 {len(executor.execution_history)} 个步骤。\n\n{results_summary}"
                        yield ChatEvent.message(final_msg)
                        has_message = True

                elif event_type == "end":
                    # Ensure a message was sent
                    if not has_message:
                        # Try to generate a response from execution history
                        if executor.execution_history:
                            results_summary = "\n\n".join([
                                f"步骤 {record.step}: {record.observation[:200]}"
                                for record in executor.execution_history
                            ])
                            yield ChatEvent.message(f"任务完成。\n\n{results_summary}")
                        else:
                            yield ChatEvent.message("任务完成，无执行结果。")
                    # Forward end event directly
                    yield {
                        "type": "end",
                        "timestamp": datetime.utcnow().isoformat()
                    }

                elif event_type == "phase":
                    # Forward phase events
                    yield event

                else:
                    # Pass through other events
                    yield event

            return

        try:
            # For Plan mode - simple and focused experience
            if enable_planning:
                # Show a brief status indicator during planning (don't stream raw decision reasoning)
                yield {
                    "type": "thinking_start",
                    "message": "正在分析任务..."
                }

                # Collect thinking content for logging only (not for display)
                thinking_log = []

                def add_thinking(content):
                    thinking_log.append(content)

                # Create the plan with deep thinking callback and tool filtering
                allowed_tools = agent_config.get("tools", []) if agent_config else None
                # 注意：allowed_tools=[] 表示agent没配置工具，需要保留[]而非转为None

                # Merge tools declared by bound skills
                if agent_config:
                    skill_names = agent_config.get("skills", [])
                    if skill_names:
                        try:
                            from app.skills.registry import get_skill_registry
                            registry = get_skill_registry()
                            if not registry._loaded:
                                registry.initialize()
                            skill_tools = []
                            for sn in skill_names:
                                skill = registry.get_skill(sn)
                                if skill and skill.tools:
                                    skill_tools.extend(skill.tools)
                            if skill_tools:
                                tool_set = set(allowed_tools) if allowed_tools else set()
                                tool_set.update(skill_tools)
                                allowed_tools = list(tool_set)
                                logger.info(f"Planning: Merged skill tools: {skill_tools}")
                        except Exception as e:
                            logger.warning(f"Failed to merge skill tools: {e}")
                # Get enabled MCP servers from agent config
                enabled_mcp_servers = None
                if agent_config:
                    agent_mcp_servers = agent_config.get("mcp_servers", [])
                    if agent_mcp_servers and isinstance(agent_mcp_servers, list):
                        enabled_server_ids = []
                        for server_config in agent_mcp_servers:
                            if isinstance(server_config, dict) and server_config.get("enabled", False):
                                enabled_server_ids.append(server_config.get("server_id"))
                            elif isinstance(server_config, str):
                                enabled_server_ids.append(server_config)
                        if enabled_server_ids:
                            enabled_mcp_servers = enabled_server_ids

                    # Auto-enable MCP servers that provide skill-declared tools
                    if skill_tools:
                        from app.core.tool_manager import get_tool_manager
                        tm = get_tool_manager()
                        skill_mcp_servers = await tm.get_mcp_server_ids_for_tools(skill_tools)
                        if skill_mcp_servers:
                            if enabled_mcp_servers is None:
                                enabled_mcp_servers = list(skill_mcp_servers)
                            else:
                                existing = set(enabled_mcp_servers)
                                for sid in skill_mcp_servers:
                                    if sid not in existing:
                                        enabled_mcp_servers.append(sid)
                                        existing.add(sid)
                            logger.info(f"Planning: Auto-enabled MCP servers for skill tools: {skill_mcp_servers}")

                plan = await decision_engine.analyze_task(
                    message,
                    conversation_history,
                    deep_thinking=True,
                    thinking_callback=add_thinking,
                    allowed_tools=allowed_tools if allowed_tools is not None else None,
                    enabled_mcp_servers=enabled_mcp_servers
                )

                # Log the thinking content for debugging but don't stream to user
                if thinking_log:
                    logger.debug(f"Decision engine thinking: {''.join(thinking_log)[:500]}...")

                # End thinking phase before showing plan
                yield {
                    "type": "thinking_end",
                    "message": "分析完成"
                }

                # Show the planning card
                yield ChatEvent.planning({
                    "complexity": plan.complexity.value,
                    "strategy": plan.strategy.value,
                    "description": plan.description,
                    "step_count": len(plan.steps)
                })

                if plan.steps:
                    # Execute the plan
                    results = {}
                    for step in plan.steps:
                        yield ChatEvent.step_start({
                            "step_id": step.step_id,
                            "tool_name": step.tool_name,
                            "step_number": len(results) + 1,
                            "total_steps": len(plan.steps),
                            "arguments": step.arguments
                        })

                        try:
                            result = await execution_engine._execute_step(step)

                            if step.status == "completed":
                                yield ChatEvent.step_complete(step.step_id, result)
                                results[step.step_id] = result
                            else:
                                yield ChatEvent.step_error(step.step_id, step.error or "Execution failed")

                        except Exception as e:
                            error_msg = str(e)
                            logger.error(f"Error executing step {step.step_id}: {error_msg}")
                            yield ChatEvent.step_error(step.step_id, error_msg)

                    # Generate final response based on execution results
                    if results:
                        results_summary = "\n\n".join([
                            f"步骤 {i+1} ({step_id}): {json.dumps(result, ensure_ascii=False)[:500]}"
                            for i, (step_id, result) in enumerate(results.items())
                        ])
                    else:
                        results_summary = "所有工具调用均失败，无执行结果。"

                    messages = []

                    # Add conversation history
                    if conversation_history:
                        messages.extend(conversation_history[-5:])

                    # Add system message with tool results
                    system_prompt = f"""你是一个智能助手。你刚刚执行了一些工具调用来帮助用户。

工具执行结果：
{results_summary}

请基于以上工具执行结果，给用户一个清晰、有用的回复。如果工具执行出错，请解释原因并提出建议。"""

                    # Add user message (skip if already the last message in history)
                    last_msg = conversation_history[-1] if conversation_history else None
                    if not (last_msg and last_msg.get("role") == "user" and last_msg.get("content") == message):
                        messages.append({
                            "role": "user",
                            "content": message
                        })

                    # Stream the response
                    async for text in self._stream_chat_with_system(messages, system_prompt):
                        yield ChatEvent.message(text)

                    yield ChatEvent.done()
                    return

                elif plan.strategy == ExecutionStrategy.THINKING:
                    # Pure thinking/planning task - use strategy_router with deep thinking
                    yield ChatEvent.thinking("深度思考中...")

                    from app.core.strategy_router import strategy_router

                    async for event in strategy_router.execute(
                        message,
                        conversation_history=conversation_history,
                        deep_thinking=True
                    ):
                        yield event

                    return

                else:
                    # No steps and not thinking strategy — use deep thinking as fallback
                    # This happens when the LLM decides no tools are needed
                    logger.info(f"Plan has no steps (strategy={plan.strategy.value}), using deep thinking")

                    from app.core.strategy_router import strategy_router

                    async for event in strategy_router.execute(
                        message,
                        conversation_history=conversation_history,
                        agent_config=agent_config,
                        deep_thinking=True
                    ):
                        yield event

                    return

            # Fallback: Direct chat without planning
            messages = self._build_messages(message, conversation_history)

            async for text in self._stream_chat(messages):
                yield ChatEvent.message(text)

            yield ChatEvent.done()

        except Exception as e:
            logger.error(f"Error in planning chat: {e}")
            yield ChatEvent.message(f"Error: {str(e)}")
            yield ChatEvent.done()

    async def _generate_final_response(
        self,
        user_message: str,
        tool_results: Dict[str, Any],
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """Generate final response based on tool execution results

        Args:
            user_message: Original user message
            tool_results: Results from tool executions
            conversation_history: Conversation history

        Returns:
            Final response
        """
        # Format tool results for the prompt
        results_summary = "\n\n".join([
            f"步骤 {i+1} ({step_id}): {json.dumps(result, ensure_ascii=False)[:500]}"
            for i, (step_id, result) in enumerate(tool_results.items())
        ])

        messages = []

        # Add conversation history
        if conversation_history:
            messages.extend(conversation_history[-5:])  # Last 5 messages

        # Inject time reminder after history, before current message
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        messages.append({
            "role": "system",
            "content": f"【提醒】当前日期时间：{current_time}，请基于此时间回答问题。"
        })

        # Add user message (skip if already the last message in history)
        last_msg = conversation_history[-1] if conversation_history else None
        if not (last_msg and last_msg.get("role") == "user" and last_msg.get("content") == user_message):
            messages.append({
                "role": "user",
                "content": user_message
            })

        # Use LLMService with system prompt
        system_message = f"""你是一个智能助手。你刚刚执行了一些工具调用来帮助用户。

工具执行结果：
{results_summary}

请基于以上工具执行结果，给用户一个清晰、有用的回复。如果工具执行出错，请解释原因并提出建议。"""

        response = await self.llm._chat_completion(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            system_prompt=system_message
        )
        return response

    async def _stream_chat(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        """Stream chat response using LLMService

        Args:
            messages: Message list

        Yields:
            Text chunks
        """
        async for content in self.llm._chat_completion_stream(messages):
            yield content

    async def _stream_chat_with_system(self, messages: List[Dict], system_prompt: str) -> AsyncGenerator[str, None]:
        """Stream chat response with system prompt using LLMService

        Args:
            messages: Message list
            system_prompt: System prompt

        Yields:
            Text chunks
        """
        async for content, _ in self.llm._chat_completion_stream_with_thinking(
            messages,
            system_prompt=system_prompt,
            enable_thinking=False
        ):
            if content is not None:
                yield content

    def _build_messages(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """Build message list

        Args:
            message: Current message
            conversation_history: Conversation history

        Returns:
            Message list
        """
        messages = []

        if conversation_history:
            messages.extend(conversation_history[-10:])  # Last 10 messages

        # Inject time reminder after history, before current message
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        messages.append({
            "role": "system",
            "content": f"【提醒】当前日期时间：{current_time}，请基于此时间回答问题。"
        })

        # Add user message (skip if already the last message in history)
        last_msg = conversation_history[-1] if conversation_history else None
        if not (last_msg and last_msg.get("role") == "user" and last_msg.get("content") == message):
            messages.append({
                "role": "user",
                "content": message
            })

        return messages

    def is_configured(self) -> bool:
        """Check if service is configured

        Returns:
            True if configured
        """
        return self.llm.is_configured()


# Global instance
planning_chat_service = PlanningChatService()
