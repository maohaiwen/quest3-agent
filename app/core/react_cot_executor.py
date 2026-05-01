"""
ReAct + 思维链模式执行器 (ReActCot)

特点：
1. 使用火山引擎官方 tool_calls 机制，不再使用脆弱的正则解析
2. 思考 → 工具调用 → 观察 循环
3. 单个连贯的思维链容器
4. 完全兼容现有前端事件
"""

import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.config import settings
from app.services.llm_service import llm_service
from app.core.tool_manager import get_tool_manager

logger = logging.getLogger(__name__)


class CotPhase(str, Enum):
    """思维链阶段"""
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    OBSERVING = "observing"
    SUMMARIZING = "summarizing"
    COMPLETE = "complete"


@dataclass
class ReActCotStep:
    """单步执行记录"""
    step_number: int
    thinking: str = ""
    tool_name: str = ""
    tool_args: Dict[str, Any] = None
    observation: Any = None
    phase: CotPhase = CotPhase.THINKING
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.tool_args is None:
            self.tool_args = {}


class ReActCotExecutor:
    """
    ReAct + 思维链执行器

    使用火山引擎的深度思考能力 + 官方 tool_calls 机制
    """

    def __init__(
        self,
        agent_config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化 ReAct Cot 执行器

        Args:
            agent_config: Agent 配置字典
        """
        self.agent_config = agent_config or {}

        # 配置
        self.model = self.agent_config.get("model", settings.VOLCENGINE_MODEL)
        self.temperature = self.agent_config.get("temperature", 0.7) or 0.7
        self.max_tokens = self.agent_config.get("max_tokens", 8192) or 8192
        self.max_steps = self.agent_config.get("max_react_steps", 15)
        self.thinking_effort = self.agent_config.get("thinking_effort", "medium")
        self.system_prompt = self.agent_config.get("system_prompt", "")

        # 状态
        self.current_step: int = 0
        self.execution_history: List[ReActCotStep] = []
        self.available_tools: Dict[str, Any] = {}
        self._is_paused = False
        self._should_stop = False

    async def execute(
        self,
        task: str,
        conversation_history: Optional[List[Dict]] = None,
        deep_thinking: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        执行任务

        Args:
            task: 用户任务描述
            conversation_history: 对话历史
            deep_thinking: 是否启用深度思考（始终启用）

        Yields:
            执行事件字典
        """
        # 初始化
        await self._initialize()
        self.current_step = 0

        logger.info(f"ReActCot: 开始执行任务 (最大步数: {self.max_steps})")

        # 发送一个开始事件，前端创建容器（只发送一次！）
        yield {"type": "cot_step_start", "step": 1}

        # 初始化 messages
        messages: List[Dict] = []

        # 添加 system prompt
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        # 添加对话历史
        if conversation_history:
            messages.extend(conversation_history)

        # 添加当前任务
        messages.append({"role": "user", "content": task})

        # 使用统一工具管理器获取 LLM 格式的工具
        tool_manager = get_tool_manager()
        agent_mcp_servers = self.agent_config.get("mcp_servers", [])
        enabled_server_ids = []
        if agent_mcp_servers and isinstance(agent_mcp_servers, list):
            for server_config in agent_mcp_servers:
                if isinstance(server_config, dict) and server_config.get("enabled", False):
                    enabled_server_ids.append(server_config.get("server_id"))
                elif isinstance(server_config, str):
                    enabled_server_ids.append(server_config)

        agent_tools = self.agent_config.get("tools", [])
        tools = await tool_manager.get_tools_for_llm(
            enabled_mcp_servers=enabled_server_ids if enabled_server_ids else None,
            allowed_tools=agent_tools if agent_tools is not None else None
        )

        logger.info(f"ReActCot: 已为 LLM 准备 {len(tools)} 个工具")

        try:
            # 主循环
            for step in range(1, self.max_steps + 1):
                if self._should_stop:
                    logger.info("ReActCot: 用户停止执行")
                    break

                self.current_step = step
                step_record = ReActCotStep(step_number=step)

                # 1. 调用 LLM，获取思考内容 + 可能的工具调用
                logger.info(f"ReActCot: 步骤 {step} - 调用 LLM")
                yield {"type": "cot_phase", "phase": "thinking"}

                thinking_content = ""
                final_content = ""
                tool_calls_to_execute = []
                tool_calls_accumulator = {}

                stream = llm_service._chat_completion_stream_with_tools(
                    messages,
                    tools=tools,
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    enable_thinking=True,
                    reasoning_effort=self.thinking_effort
                )

                async for event in stream:
                    if event["type"] == "thinking":
                        thinking_content += event["content"]
                        yield {"type": "cot_thinking", "content": event["content"], "step": step}

                    elif event["type"] == "content":
                        final_content += event["content"]

                    elif event["type"] == "tool_calls":
                        # 累加 tool_calls
                        for tc in event["tool_calls"]:
                            idx = tc["index"]
                            if idx not in tool_calls_accumulator:
                                tool_calls_accumulator[idx] = tc
                            else:
                                tool_calls_accumulator[idx]["function"]["arguments"] += tc["function"]["arguments"]

                    elif event["type"] == "done":
                        break

                step_record.thinking = thinking_content
                self.execution_history.append(step_record)

                # 转换为 list
                if tool_calls_accumulator:
                    tool_calls_to_execute = list(tool_calls_accumulator.values())

                logger.info(f"ReActCot: 步骤 {step} - 思考完成, 有工具调用: {len(tool_calls_to_execute)}")

                # 添加 assistant message 到历史
                assistant_msg = {"role": "assistant", "content": final_content}
                if tool_calls_to_execute:
                    assistant_msg["tool_calls"] = tool_calls_to_execute
                messages.append(assistant_msg)

                # 2. 判断是否有工具调用
                if tool_calls_to_execute:
                    # 有工具调用，执行
                    for tool_call in tool_calls_to_execute:
                        tool_name = tool_call["function"]["name"]
                        tool_args_str = tool_call["function"]["arguments"]
                        try:
                            tool_args = json.loads(tool_args_str)
                        except:
                            tool_args = {}

                        step_record.tool_name = tool_name
                        step_record.tool_args = tool_args
                        step_record.phase = CotPhase.TOOL_CALL

                        yield {"type": "cot_phase", "phase": "tool-call"}
                        yield {
                            "type": "cot_action",
                            "tool_name": tool_name,
                            "tool_args": tool_args
                        }

                        # 3. 执行工具
                        logger.info(f"ReActCot: 步骤 {step} - 执行工具: {tool_name}")
                        yield {"type": "cot_phase", "phase": "observation"}

                        observation = await self._execute_tool(tool_name, tool_args)
                        step_record.observation = observation
                        step_record.phase = CotPhase.OBSERVING

                        yield {
                            "type": "cot_observation",
                            "result": observation
                        }

                        # 添加 tool response 到历史
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": json.dumps(observation, ensure_ascii=False)
                        })

                else:
                    # 没有工具调用，任务完成
                    logger.info(f"ReActCot: 模型决定结束任务")
                    yield {"type": "cot_phase", "phase": "summarizing"}
                    yield {"type": "cot_phase", "phase": "complete"}
                    yield {"type": "cot_complete", "message": final_content or thinking_content}
                    yield {"type": "end"}
                    break

                await asyncio.sleep(0.01)

            else:
                # 达到最大步数
                logger.warning(f"ReActCot: 达到最大步数 {self.max_steps}")
                yield {
                    "type": "error",
                    "message": f"已达到最大执行步数 ({self.max_steps})，任务未完成"
                }

        except Exception as e:
            logger.error(f"ReActCot: 执行错误: {e}", exc_info=True)
            yield {"type": "error", "message": f"执行错误: {str(e)}"}
            yield {"type": "end"}

        finally:
            logger.info("ReActCot: 执行结束")
            # 始终确保发送 end 事件
            yield {"type": "end"}

    async def _initialize(self):
        """初始化执行器"""
        self.execution_history = []
        self.current_step = 0

        # 获取 Agent 启用的 MCP 服务器
        agent_mcp_servers = self.agent_config.get("mcp_servers", [])
        enabled_server_ids = []
        if agent_mcp_servers and isinstance(agent_mcp_servers, list):
            for server_config in agent_mcp_servers:
                if isinstance(server_config, dict) and server_config.get("enabled", False):
                    enabled_server_ids.append(server_config.get("server_id"))
                elif isinstance(server_config, str):
                    enabled_server_ids.append(server_config)

        logger.info(f"ReActCot: Agent 已启用 {len(enabled_server_ids)} 个 MCP 服务器: {enabled_server_ids}")

        # 获取 Agent 的工具白名单
        agent_tools = self.agent_config.get("tools", [])

        # 使用统一工具管理器获取可用工具
        tool_manager = get_tool_manager()
        tools_dict = await tool_manager.get_available_tools(
            enabled_mcp_servers=enabled_server_ids,
            allowed_tools=agent_tools if agent_tools is not None else None
        )

        # 转换为LLM需要的格式（存储在self.available_tools中，格式保持兼容）
        self.available_tools = {}
        for tool_name, tool_def in tools_dict.items():
            self.available_tools[tool_name] = {
                "name": tool_def.name,
                "description": tool_def.description,
                "input_schema": tool_def.input_schema,
                "server_id": tool_def.server_id,
                "source": tool_def.source
            }

        logger.info(f"ReActCot: 总共可用 {len(self.available_tools)} 个工具: {list(self.available_tools.keys())}")

    async def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """执行工具调用"""
        try:
            logger.info(f"ReActCot: 调用工具 {tool_name}, 参数: {tool_args}")

            tool_manager = get_tool_manager()
            result = await tool_manager.call_tool(tool_name, tool_args)

            logger.info(f"ReActCot: 工具 {tool_name} 执行完成，结果类型: {type(result)}")
            return result

        except Exception as e:
            logger.error(f"ReActCot: 工具 {tool_name} 执行错误: {e}")
            return {'error': str(e)}

    def pause(self):
        """暂停执行"""
        self._is_paused = True

    def resume(self):
        """继续执行"""
        self._is_paused = False

    def stop(self):
        """停止执行"""
        self._should_stop = True
