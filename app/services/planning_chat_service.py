"""Intelligent chat service with planning and execution capabilities"""
import logging
import json
from typing import Optional, AsyncGenerator, List, Dict, Any
from datetime import datetime

from anthropic import AsyncAnthropic
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

    def __init__(self, api_key: Optional[str] = None):
        """Initialize service

        Args:
            api_key: Anthropic API key
        """
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS

        self.client = AsyncAnthropic(api_key=self.api_key) if self.api_key else None

    def set_client(self, client):
        """Set LLM client

        Args:
            client: AsyncAnthropic client
        """
        self.client = client

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
        if not self.client:
            yield ChatEvent.message("LLM not configured. Please set ANTHROPIC_API_KEY.")
            yield ChatEvent.done()
            return

        # Use ReAct executor for react mode
        if use_react:
            from app.core.react_executor import ReActExecutor

            # Merge agent config with service config
            merged_config = {
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if agent_config:
                merged_config.update(agent_config)

            executor = ReActExecutor(
                agent_config=merged_config,
                llm_client=self.client
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
                # First, show thinking start and do planning with streaming thinking content
                yield {
                    "type": "thinking_start",
                    "message": "分析任务并规划执行方案..."
                }

                # Collect thinking content
                thinking_content = []

                def add_thinking(content):
                    thinking_content.append(content)

                # Create the plan with deep thinking callback and tool filtering
                allowed_tools = agent_config.get("tools", []) if agent_config else None
                # 注意：allowed_tools=[] 表示agent没配置工具，需要保留[]而非转为None
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

                plan = await decision_engine.analyze_task(
                    message,
                    conversation_history,
                    deep_thinking=True,
                    thinking_callback=add_thinking,
                    allowed_tools=allowed_tools if allowed_tools is not None else None,
                    enabled_mcp_servers=enabled_mcp_servers
                )

                # Yield the thinking content that was collected
                for thought in thinking_content:
                    yield ChatEvent.thinking(thought)

                # Show the planning card
                yield ChatEvent.planning({
                    "complexity": plan.complexity.value,
                    "strategy": plan.strategy.value,
                    "description": plan.description,
                    "step_count": len(plan.steps)
                })

                # End thinking phase
                yield {
                    "type": "thinking_end",
                    "message": "规划完成"
                }

                if plan.steps:
                    # Execute the plan
                    yield ChatEvent.thinking("执行工具调用计划...")

                    execution_context = {
                        "user_message": message,
                        "conversation_history": conversation_history or []
                    }

                    results = {}
                    for step in plan.steps:
                        yield ChatEvent.step_start({
                            "step_id": step.step_id,
                            "tool_name": step.tool_name,
                            "step_number": len(results) + 1,
                            "total_steps": len(plan.steps)
                        })

                        try:
                            yield ChatEvent.step_progress(
                                step.step_id,
                                f"调用工具: {step.tool_name}..."
                            )

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

                    # Step 2: Generate final response based on execution results - with streaming!
                    yield ChatEvent.thinking("生成最终回复...")

                    # Stream the final response
                    results_summary = "\n\n".join([
                        f"步骤 {i+1} ({step_id}): {json.dumps(result, ensure_ascii=False)[:500]}"
                        for i, (step_id, result) in enumerate(results.items())
                    ])

                    messages = []

                    # Add conversation history
                    if conversation_history:
                        messages.extend(conversation_history[-5:])

                    # Add system message with tool results
                    system_prompt = f"""你是一个智能助手。你刚刚执行了一些工具调用来帮助用户。

工具执行结果：
{results_summary}

请基于以上工具执行结果，给用户一个清晰、有用的回复。如果工具执行出错，请解释原因并提出建议。"""

                    # Add user message
                    messages.append({
                        "role": "user",
                        "content": message
                    })

                    # Stream the response
                    yield {
                        "type": "message_start"
                    }

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

        # Add system message
        system_message = f"""你是一个智能助手。你刚刚执行了一些工具调用来帮助用户。

工具执行结果：
{results_summary}

请基于以上工具执行结果，给用户一个清晰、有用的回复。如果工具执行出错，请解释原因并提出建议。
"""

        # Add user message
        messages.append({
            "role": "user",
            "content": user_message
        })

        # Get response
        response = await self.client.messages.create(
            model=self.model,
            system=system_message,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature
        )

        text_blocks = [block.text for block in response.content if block.type == "text"]
        return "".join(text_blocks)

    async def _stream_chat(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        """Stream chat response

        Args:
            messages: Message list

        Yields:
            Text chunks
        """
        async with self.client.messages.stream(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def _stream_chat_with_system(self, messages: List[Dict], system_prompt: str) -> AsyncGenerator[str, None]:
        """Stream chat response with system prompt

        Args:
            messages: Message list
            system_prompt: System prompt

        Yields:
            Text chunks
        """
        async with self.client.messages.stream(
            model=self.model,
            system=system_prompt,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature
        ) as stream:
            async for text in stream.text_stream:
                yield text

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
        return bool(self.api_key)


# Global instance
planning_chat_service = PlanningChatService()
