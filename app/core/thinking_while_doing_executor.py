
"""Thinking-While-Doing mode executor - 边想边干模式

这种模式利用深度思考模型的思维链能力，在单次或少量调用中完成任务：
1. 模型在思维链中模拟工具调用和观察
2. 对于必须真实执行的工具（如文件写入、代码执行），解析思维链并真实调用
3. 将真实结果传回模型继续思考/总结
"""
import asyncio
import json
import logging
import re
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.config import settings
from app.models.agent import AgentExecutionMode
from app.core.tool_manager import get_tool_manager

logger = logging.getLogger(__name__)


class CotActionType(str, Enum):
    """思维链中的动作类型"""
    THINK = "think"          # 只是思考
    TOOL_CALL = "tool_call"  # 工具调用
    SIMULATE = "simulate"    # 内部模拟（不需要真实执行）
    COMPLETE = "complete"    # 任务完成


@dataclass
class CotAction:
    """解析出的思维链动作"""
    action_type: CotActionType
    thought: str = ""
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    requires_real_exec: bool = False  # 是否需要真实执行
    final_message: str = ""


@dataclass
class CotExecutionRecord:
    """执行记录"""
    phase: str  # "thinking", "action", "observation"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ThinkingWhileDoingExecutor:
    """边想边干模式执行器"""

    # 需要真实执行的工具列表
    REAL_EXEC_TOOLS = {
        "write_file", "read_file", "edit_file", "delete_file",
        "run_code", "run_tests", "execute_command",
        "web_search", "browser_navigate", "click_element",
        # 添加其他需要真实执行的工具
    }

    def __init__(
        self,
        agent_config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Thinking-While-Doing executor

        Args:
            agent_config: Agent configuration
        """
        self.agent_config = agent_config or {}

        # Configuration
        self.model = self.agent_config.get("model", settings.VOLCENGINE_MODEL)
        self.temperature = self.agent_config.get("temperature", 0.7) or 0.7
        self.max_tokens = self.agent_config.get("max_tokens", 8192) or 8192
        self.system_prompt = self.agent_config.get("system_prompt", "")
        self.reasoning_effort = self.agent_config.get("reasoning_effort", "medium")

        # Execution state
        self.execution_history: List[CotExecutionRecord] = []
        self.available_tools: Dict[str, Any] = {}
        self.full_reasoning_trace: List[str] = []

    async def execute(
        self,
        task: str,
        conversation_history: Optional[List[Dict]] = None,
        deep_thinking: bool = True,  # 兼容ReActExecutor接口
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行任务 - 边想边干模式

        Args:
            task: 用户任务描述
            conversation_history: 对话历史

        Yields:
            执行事件
        """
        # Initialize
        await self._initialize()

        # Phase 1: 第一次深度思考 - 规划并尝试模拟执行
        logger.info("ThinkingWhileDoing: Phase 1 - Initial deep thinking")
        yield {
            "type": "thinking_start",
            "message": "边想边干模式启动中...",
            "mode": "thinking_while_doing"
        }

        # 构建第一次调用的上下文
        context = self._build_initial_context(task, conversation_history)

        # 调用深度思考模型
        try:
            from app.services.llm_service import llm_service

            # 第一次调用：完整思维链
            messages = [{"role": "user", "content": context}]

            thinking_trace = []
            final_content = ""

            # 流式获取思维链和内容
            async for content, thinking in llm_service._chat_completion_stream_with_thinking(
                messages,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                system_prompt=self._build_cot_system_prompt(),
                enable_thinking=True,
                reasoning_effort=self.reasoning_effort
            ):
                if thinking is not None:
                    thinking_trace.append(thinking)
                    yield {
                        "type": "thinking",
                        "message": thinking,
                        "mode": "thinking_while_doing"
                    }
                elif content is not None:
                    final_content += content

            full_reasoning = "".join(thinking_trace)
            self.full_reasoning_trace.append(full_reasoning)

            # 解析思维链，提取需要真实执行的动作
            logger.info("ThinkingWhileDoing: Parsing reasoning chain for actions")
            actions = self._parse_cot_actions(full_reasoning)

            # 检查是否有需要真实执行的工具
            real_actions = [a for a in actions if a.requires_real_exec and a.action_type == CotActionType.TOOL_CALL]

            if real_actions:
                logger.info(f"ThinkingWhileDoing: Found {len(real_actions)} actions requiring real execution")

                # Phase 2: 执行真实工具调用
                tool_results = []
                for idx, action in enumerate(real_actions):
                    logger.info(f"ThinkingWhileDoing: Executing real tool {idx + 1}/{len(real_actions)}: {action.tool_name}")

                    yield {
                        "type": "action_start",
                        "step": idx + 1,
                        "tool_name": action.tool_name,
                        "arguments": action.arguments,
                        "thought": action.thought,
                        "mode": "thinking_while_doing"
                    }

                    # 真实执行工具
                    observation = await self._execute_real_tool(action)

                    yield {
                        "type": "observation",
                        "step": idx + 1,
                        "tool_name": action.tool_name,
                        "result": self._format_observation(observation),
                        "mode": "thinking_while_doing"
                    }

                    tool_results.append({
                        "tool_name": action.tool_name,
                        "arguments": action.arguments,
                        "result": observation
                    })

                    self.execution_history.append(CotExecutionRecord(
                        phase="action",
                        content=f"Executed {action.tool_name}: {json.dumps(action.arguments, ensure_ascii=False)}"
                    ))
                    self.execution_history.append(CotExecutionRecord(
                        phase="observation",
                        content=str(observation)
                    ))

                # Phase 3: 第二次深度思考 - 基于真实结果总结
                logger.info("ThinkingWhileDoing: Phase 3 - Final reasoning with real results")

                final_context = self._build_final_context(
                    task, full_reasoning, tool_results, conversation_history
                )

                final_thinking_trace = []
                final_answer = ""

                final_messages = [{"role": "user", "content": final_context}]

                async for content, thinking in llm_service._chat_completion_stream_with_thinking(
                    final_messages,
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    system_prompt="请基于以上真实执行结果，给出最终总结。",
                    enable_thinking=True,
                    reasoning_effort="low"
                ):
                    if thinking is not None:
                        final_thinking_trace.append(thinking)
                        yield {
                            "type": "thinking",
                            "message": thinking,
                            "mode": "thinking_while_doing"
                        }
                    elif content is not None:
                        final_answer += content

                self.full_reasoning_trace.append("".join(final_thinking_trace))

                # 输出最终答案
                yield {
                    "type": "complete",
                    "message": final_answer or final_content,
                    "mode": "thinking_while_doing",
                    "reasoning_trace": "\n---\n".join(self.full_reasoning_trace)
                }

            else:
                # 不需要真实执行，直接输出结果
                logger.info("ThinkingWhileDoing: No real execution needed, completing directly")
                yield {
                    "type": "complete",
                    "message": final_content,
                    "mode": "thinking_while_doing",
                    "reasoning_trace": full_reasoning
                }

            # 结束
            await asyncio.sleep(0.1)
            yield {"type": "end"}

        except Exception as e:
            logger.error(f"Error in ThinkingWhileDoing execution: {e}")
            yield {
                "type": "error",
                "error": str(e),
                "mode": "thinking_while_doing"
            }

    async def _initialize(self):
        """初始化执行器状态"""
        self.execution_history = []
        self.full_reasoning_trace = []

        # 获取Agent配置的MCP服务器
        agent_mcp_servers = self.agent_config.get("mcp_servers", [])
        enabled_server_ids = []
        if agent_mcp_servers and isinstance(agent_mcp_servers, list):
            for server_config in agent_mcp_servers:
                if isinstance(server_config, dict) and server_config.get("enabled", False):
                    enabled_server_ids.append(server_config.get("server_id"))
                elif isinstance(server_config, str):
                    enabled_server_ids.append(server_config)

        # 获取Agent配置的工具白名单
        agent_allowed_tools = self.agent_config.get("tools", [])

        # 使用统一工具管理器获取可用工具
        tool_manager = get_tool_manager()
        tools_dict = await tool_manager.get_available_tools(
            enabled_mcp_servers=enabled_server_ids if enabled_server_ids else None,
            allowed_tools=agent_allowed_tools if agent_allowed_tools is not None else None
        )

        # 转换为兼容格式
        self.available_tools = {}
        for tool_name, tool_def in tools_dict.items():
            self.available_tools[tool_name] = {
                "name": tool_def.name,
                "description": tool_def.description,
                "input_schema": tool_def.input_schema,
                "server_id": tool_def.server_id,
                "source": tool_def.source
            }

        logger.info(f"ThinkingWhileDoing initialized with {len(self.available_tools)} tools: {list(self.available_tools.keys())}")

    def _build_cot_system_prompt(self) -> str:
        """构建思维链模式的系统提示词"""
        base_prompt = """你是一个"边想边干"的智能助手。

思考格式：
- 思考: [分析问题，制定计划]
- 行动: 调用 工具名(参数名1=值1,参数名2=值2)
- 观察: [工具返回的结果]
- 完成: [最终回复给用户的消息]

重要：以下工具必须标记 [需要真实执行]，不要模拟结果：
- write_file, read_file, edit_file, delete_file
- run_code, run_tests, execute_command
- web_search, browser_*

示例：
思考: 用户需要写一个Python函数计算斐波那契数列，我先写代码再测试。
行动: [需要真实执行] 调用 write_file(file_name="fib.py", content="def fib(n):...")
观察: [等待执行结果]
思考: 好的，文件已写入，现在测试一下。
行动: [需要真实执行] 调用 run_code(code="...")
观察: 输出结果显示正常
完成: 任务完成！函数已经写好并测试通过...
"""
        if self.system_prompt:
            return f"{self.system_prompt}\n\n{base_prompt}"
        return base_prompt

    def _build_initial_context(
        self,
        task: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """构建初始上下文"""
        context_parts = []

        # 添加任务
        context_parts.append(f"# 当前任务\n{task}\n")

        # 添加可用工具
        context_parts.append("\n# 可用工具\n")
        for tool_name, tool_info in self.available_tools.items():
            context_parts.append(f"- {tool_name}: {tool_info.get('description', '')}")
            if tool_info.get("input_schema"):
                params = tool_info["input_schema"].get("properties", {})
                required = tool_info["input_schema"].get("required", [])
                if params:
                    context_parts.append("  参数:")
                    for param_name, param_info in params.items():
                        req_mark = " *" if param_name in required else ""
                        param_type = param_info.get("type", "string")
                        param_desc = param_info.get("description", "")
                        context_parts.append(f"    - {param_name} ({param_type}){req_mark}: {param_desc}")

        # 添加对话历史
        if conversation_history:
            context_parts.append("\n# 对话历史\n")
            for msg in conversation_history[-5:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")[:300]
                context_parts.append(f"{role}: {content}")

        context_parts.append("\n请开始边想边干：")
        return "\n".join(context_parts)

    def _build_final_context(
        self,
        task: str,
        initial_reasoning: str,
        tool_results: List[Dict],
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """构建最终总结的上下文"""
        context_parts = []

        context_parts.append(f"# 原始任务\n{task}\n")
        context_parts.append(f"# 初步思考过程\n{initial_reasoning}\n")

        context_parts.append("\n# 真实工具执行结果\n")
        for idx, result in enumerate(tool_results, 1):
            context_parts.append(f"## 工具 {idx}: {result['tool_name']}")
            context_parts.append(f"参数: {json.dumps(result['arguments'], ensure_ascii=False)}")
            context_parts.append(f"结果: {json.dumps(result['result'], ensure_ascii=False)[:1000]}")

        context_parts.append("\n请基于以上真实执行结果，给出最终总结。")
        return "\n".join(context_parts)

    def _parse_cot_actions(self, reasoning_content: str) -> List[CotAction]:
        """解析思维链，提取动作

        Args:
            reasoning_content: 思维链内容

        Returns:
            动作列表
        """
        actions = []

        # 按行处理
        lines = reasoning_content.split('\n')

        current_thought = ""
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # 匹配思考
            thought_match = re.match(r'^思考[：:]\s*(.*)$', line)
            if thought_match:
                current_thought = thought_match.group(1).strip()
                # 继续收集后续的思考行
                i += 1
                while i < len(lines):
                    next_line = lines[i].strip()
                    if any([
                        re.match(r'^行动[：:]\s*', next_line),
                        re.match(r'^观察[：:]\s*', next_line),
                        re.match(r'^完成[：:]\s*', next_line)
                    ]):
                        break
                    if next_line:
                        current_thought += "\n" + next_line
                    i += 1
                continue

            # 匹配行动
            action_match = re.match(r'^行动[：:]\s*(.*)$', line)
            if action_match:
                action_content = action_match.group(1).strip()

                # 检查是否需要真实执行
                requires_real = "[需要真实执行]" in action_content
                action_content = action_content.replace("[需要真实执行]", "").strip()

                # 解析工具调用
                tool_call_match = re.match(r'调用\s*(\w+)\s*\((.*)\)', action_content)
                if tool_call_match:
                    tool_name = tool_call_match.group(1).strip()
                    params_str = tool_call_match.group(2).strip()

                    # 解析参数
                    arguments = self._parse_parameters(params_str)

                    # 检查工具是否在真实执行列表中
                    requires_real = requires_real or tool_name in self.REAL_EXEC_TOOLS

                    actions.append(CotAction(
                        action_type=CotActionType.TOOL_CALL,
                        thought=current_thought,
                        tool_name=tool_name,
                        arguments=arguments,
                        requires_real_exec=requires_real
                    ))
                else:
                    # 只是模拟的行动
                    actions.append(CotAction(
                        action_type=CotActionType.SIMULATE,
                        thought=current_thought
                    ))
                i += 1
                continue

            # 匹配完成
            complete_match = re.match(r'^完成[：:]\s*(.*)$', line)
            if complete_match:
                actions.append(CotAction(
                    action_type=CotActionType.COMPLETE,
                    thought=current_thought,
                    final_message=complete_match.group(1).strip()
                ))
                i += 1
                continue

            i += 1

        # 如果没有解析到任何动作，至少添加一个思考动作
        if not actions and reasoning_content:
            actions.append(CotAction(
                action_type=CotActionType.THINK,
                thought=reasoning_content
            ))

        return actions

    def _parse_parameters(self, params_str: str) -> Dict[str, Any]:
        """解析参数字符串

        支持格式：
        - param1=value1,param2=value2
        - param1="value1",param2='value2'
        """
        arguments = {}

        if not params_str:
            return arguments

        # 简单的参数解析器
        import shlex

        try:
            # 替换逗号为空格，让shlex处理
            # 但要小心引号内的逗号
            parts = []
            current = ""
            in_quote = None
            for char in params_str:
                if char in ('"', "'"):
                    if in_quote == char:
                        in_quote = None
                    elif in_quote is None:
                        in_quote = char
                    current += char
                elif char == ',' and in_quote is None:
                    parts.append(current.strip())
                    current = ""
                else:
                    current += char
            if current:
                parts.append(current.strip())

            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    # 移除引号
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]

                    # 尝试解析为JSON
                    try:
                        arguments[key] = json.loads(value)
                    except:
                        arguments[key] = value

        except Exception as e:
            logger.warning(f"Failed to parse parameters: {e}, returning raw string")
            arguments["raw"] = params_str

        return arguments

    async def _execute_real_tool(self, action: CotAction) -> Any:
        """真实执行工具

        Args:
            action: 动作信息

        Returns:
            工具执行结果
        """
        tool_name = action.tool_name
        arguments = action.arguments

        logger.info(f"ThinkingWhileDoing: Real execution of {tool_name} with args: {arguments}")

        try:
            # 使用统一工具管理器执行工具
            tool_manager = get_tool_manager()
            result = await tool_manager.call_tool(tool_name, arguments)

            return result

        except Exception as e:
            logger.error(f"ThinkingWhileDoing: Error executing tool {tool_name}: {e}")
            return {"error": str(e)}

    def _format_observation(self, result: Any) -> str:
        """格式化观察结果"""
        if isinstance(result, dict):
            if "error" in result:
                return f"执行失败: {result['error']}"
            return json.dumps(result, ensure_ascii=False, indent=2)
        elif isinstance(result, (list, tuple)):
            return json.dumps(result, ensure_ascii=False, indent=2)
        else:
            return str(result)[:1000]

