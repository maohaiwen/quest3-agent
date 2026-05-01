"""ReAct mode executor using official Volcengine tool_calls mechanism"""
import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """Single execution record"""
    step: int
    thought: str
    action: Dict[str, Any]
    observation: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ReActExecutor:
    """ReAct mode executor using official Volcengine tool_calls mechanism"""

    def __init__(
        self,
        agent_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize ReAct executor

        Args:
            agent_config: Agent configuration
        """
        self.agent_config = agent_config or {}
        self.max_steps = self.agent_config.get("max_react_steps", 15)
        self.model = self.agent_config.get("model")
        self.temperature = self.agent_config.get("temperature")
        self.max_tokens = self.agent_config.get("max_tokens")
        self.system_prompt = self.agent_config.get("system_prompt", "")

        # Execution state
        self.execution_history: List[ExecutionRecord] = []

    async def execute(
        self,
        task: str,
        conversation_history: Optional[List[Dict]] = None,
        deep_thinking: bool = True
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute task using ReAct with official tool_calls

        Args:
            task: User task description
            conversation_history: Previous conversation messages
            deep_thinking: Enable deep thinking mode

        Yields:
            Execution events (same format as before for frontend compatibility)
        """
        from app.services.llm_service import llm_service
        from app.services.mcp_pool import mcp_client_pool

        # Initialize messages list
        messages: List[Dict] = []

        # Add system prompt
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        # Add conversation history
        if conversation_history:
            messages.extend(conversation_history)

        # Add user task
        messages.append({"role": "user", "content": task})

        # Get tools with filtering - only from enabled MCP servers
        agent_tools = self.agent_config.get("tools", [])
        agent_mcp_servers = self.agent_config.get("mcp_servers", [])
        enabled_server_ids = []
        if agent_mcp_servers and isinstance(agent_mcp_servers, list):
            for server_config in agent_mcp_servers:
                if isinstance(server_config, dict) and server_config.get("enabled", False):
                    enabled_server_ids.append(server_config.get("server_id"))
                elif isinstance(server_config, str):
                    enabled_server_ids.append(server_config)

        # Pass both enabled servers and allowed tools to filter
        # 注意：agent_tools=[] 表示agent没配置工具，需要传[]而非None，否则会跳过白名单过滤
        tools = await llm_service._get_tools_format(
            allowed_tools=agent_tools if agent_tools is not None else None,
            enabled_mcp_servers=enabled_server_ids if enabled_server_ids else None
        )

        yield {"type": "thinking_start", "message": "深度思考中..."}

        thinking_text = ""
        has_tool_calls = False

        # ReAct loop
        for step in range(self.max_steps):
            logger.info(f"ReAct loop step {step + 1}/{self.max_steps}")

            try:
                # First step: always think and maybe call tools
                if step == 0 or has_tool_calls:
                    # Call LLM with tool_calls
                    thinking_content = ""
                    final_content = ""
                    tool_calls_to_execute = []
                    # For accumulating tool_calls across chunks
                    tool_calls_accumulator = {}

                    # Stream the response
                    stream = llm_service._chat_completion_stream_with_tools(
                        messages,
                        tools=tools,
                        model=self.model,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        system_prompt=self.system_prompt,
                        enable_thinking=True,
                        reasoning_effort=self.agent_config.get("thinking_effort", "medium")
                    )

                    phase_sent = False
                    async for event in stream:
                        if event["type"] == "thinking":
                            thinking_content += event["content"]
                            yield {"type": "thinking", "message": event["content"]}
                            thinking_text += event["content"]

                            # Send phase event once
                            if not phase_sent:
                                phase_sent = True
                                yield {"type": "phase", "phase": "thought"}

                        elif event["type"] == "content":
                            final_content += event["content"]

                        elif event["type"] == "tool_calls":
                            has_tool_calls = True
                            # Accumulate tool_calls (might be split across chunks)
                            for tc in event["tool_calls"]:
                                idx = tc["index"]
                                if idx not in tool_calls_accumulator:
                                    tool_calls_accumulator[idx] = tc
                                else:
                                    # Accumulate arguments
                                    tool_calls_accumulator[idx]["function"]["arguments"] += tc["function"][
                                        "arguments"
                                    ]
                        elif event["type"] == "done":
                            break

                    # Convert accumulator to list and process
                    if tool_calls_accumulator:
                        tool_calls_to_execute = list(tool_calls_accumulator.values())

                    if thinking_content:
                        yield {"type": "thinking_end", "message": "思考完成"}

                    # Add assistant message (including tool_calls) to history
                    assistant_message = {"role": "assistant", "content": final_content}
                    if tool_calls_to_execute:
                        assistant_message["tool_calls"] = tool_calls_to_execute
                    messages.append(assistant_message)

                    # Record to history
                    if tool_calls_to_execute:
                        self.execution_history.append(
                            ExecutionRecord(
                                step=step + 1,
                                thought=thinking_content,
                                action={"tool_calls": tool_calls_to_execute},
                                observation=""
                            )
                        )

                    # If no tool calls, we're done
                    if not tool_calls_to_execute:
                        yield {"type": "complete", "message": final_content}
                        yield {"type": "end"}
                        break

                    # Execute tool calls
                    for tool_call in tool_calls_to_execute:
                        tool_name = tool_call["function"]["name"]
                        tool_args = json.loads(tool_call["function"]["arguments"])

                        yield {
                            "type": "action_start",
                            "step": step + 1,
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "thought": thinking_content
                        }

                        # Call tool
                        try:
                            tool_manager = get_tool_manager()
                            observation = await tool_manager.call_tool(
                                tool_name, tool_args
                            )
                        except Exception as e:
                            observation = {"error": str(e)}

                        yield {
                            "type": "observation",
                            "step": step + 1,
                            "tool_name": tool_name,
                            "result": observation
                        }

                        # Add tool message to history
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": json.dumps(observation, ensure_ascii=False)
                        })

                        # Update observation in history
                        if self.execution_history:
                            self.execution_history[-1].observation = str(observation)

                    has_tool_calls = True
                    await asyncio.sleep(0.01)

            except Exception as e:
                logger.error(f"Error in ReAct step {step + 1}: {e}", exc_info=True)
                yield {"type": "error", "message": str(e)}
                yield {"type": "end"}
                break

        else:
            yield {"type": "error", "message": f"Reached max steps {self.max_steps}"}
            yield {"type": "end"}
