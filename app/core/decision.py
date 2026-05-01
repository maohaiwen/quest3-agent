"""Tool decision engine for LLM-based tool selection"""
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from app.core.execution import ExecutionPlan, ExecutionStep, ComplexityLevel, ExecutionStrategy
from app.services.llm_service import LLMService
from app.core.tool_manager import get_tool_manager

logger = logging.getLogger(__name__)


class ToolDecisionEngine:
    """Engine for LLM-based tool decision making"""

    def __init__(self, llm_service: Optional[LLMService] = None):
        """Initialize decision engine

        Args:
            llm_service: LLM service instance
        """
        self.llm_service = llm_service

    def set_llm_service(self, llm_service: LLMService):
        """Set LLM service

        Args:
            llm_service: LLM service instance
        """
        self.llm_service = llm_service

    async def analyze_task(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict]] = None,
        deep_thinking: bool = False,
        thinking_callback: Optional[callable] = None,
        allowed_tools: Optional[List[str]] = None,
        enabled_mcp_servers: Optional[List[str]] = None
    ) -> ExecutionPlan:
        """Analyze task and create execution plan

        Args:
            user_message: User message
            conversation_history: Previous conversation
            deep_thinking: Enable deep thinking mode
            thinking_callback: Callback for streaming thinking content (sync function)
            allowed_tools: Optional list of allowed tool names. If provided, only these tools are included.
            enabled_mcp_servers: Optional list of enabled MCP server IDs. If provided, only tools from these servers are included.

        Returns:
            Execution plan
        """
        # 使用统一工具管理器获取工具
        tool_manager = get_tool_manager()
        tools = await tool_manager.get_tools_for_llm(
            enabled_mcp_servers=enabled_mcp_servers,
            allowed_tools=allowed_tools
        )

        # 同时获取工具字典用于日志
        tools_dict = await tool_manager.get_available_tools(
            enabled_mcp_servers=enabled_mcp_servers,
            allowed_tools=allowed_tools
        )

        logger.info(f"Available tools for planning: {list(tools_dict.keys())}, deep_thinking={deep_thinking}")

        # Create prompt for LLM
        prompt = self._create_decision_prompt(user_message, tools, conversation_history)

        if not self.llm_service:
            logger.warning("LLM service not set, using simple plan")
            return self._create_simple_plan(user_message)

        try:
            # Call LLM for decision
            if deep_thinking and hasattr(self.llm_service, '_chat_completion_stream_with_thinking'):
                # Use streaming with thinking support
                messages = [{"role": "user", "content": prompt}]
                full_response = ""

                async for content, thinking in self.llm_service._chat_completion_stream_with_thinking(
                    messages,
                    enable_thinking=True,
                    reasoning_effort="medium"
                ):
                    if thinking is not None and thinking_callback:
                        # Call the sync callback
                        thinking_callback(thinking)
                    if content is not None:
                        full_response += content

                response = full_response
            else:
                response = await self.llm_service.chat(prompt, use_tools=False)

            logger.info(f"LLM decision response: {response[:500]}...")

            # Parse LLM response
            plan = self._parse_llm_response(response, user_message)

            logger.info(f"Created execution plan: {plan.strategy.value}, complexity: {plan.complexity.value}, {len(plan.steps)}")
            return plan

        except Exception as e:
            logger.error(f"Error analyzing task: {e}, using simple plan")
            return self._create_simple_plan(user_message)

    def _create_decision_prompt(
        self,
        user_message: str,
        tools: str,
        conversation_history: Optional[List[Dict]]
    ) -> str:
        """Create decision prompt for LLM

        Args:
            user_message: User message
            tools: Available tools description
            conversation_history: Previous conversation

        Returns:
            Prompt string
        """
        history_str = ""
        if conversation_history:
            history_str = "\n\n对话历史：\n"
            for msg in conversation_history[-5:]:  # Last 5 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_str += f"{role}: {content}\n"

        prompt = f"""你是一个智能工具调用决策器。请分析用户请求并制定执行计划。

任务类型：
- SIMPLE: 单次工具调用即可完成（如读取文件、列出目录、简单查询、问候）
- MEDIUM: 需要 2-3 步顺序调用（如读取+分析+保存、多步骤数据处理）
- COMPLEX: 需要多步、条件判断或并行调用（如复杂数据处理、多任务协调）

执行策略：
- single: 单次调用
- chain: 链式调用（步骤按顺序执行，结果传递）
- parallel: 并行调用（同时执行多个独立步骤）
- mixed: 混合调用（并行+链式组合）
- thinking: 深度思考模式，由LLM完整思考并制定计划（适用于策划、规划类任务）

任务分类判断要点：

1. 识别为需要联网搜索的任务（必须使用工具）：
   - 查询地点、景点、餐厅、酒店等人气/评价/价格信息
   - 查询实时数据（天气、股票、新闻、赛事等）
   - 查询具体商户、地址、联系方式等
   - 关键词：哪里、哪家、最好的、推荐、排名、地址、电话、价格、评价

2. 识别为工具调用任务：
   - 需要访问外部数据（文件、网络、数据库）
   - 需要执行系统操作
   - 需要检索或查询信息

3. 识别为纯知识/创意任务（通常不需要工具）：
   - 问答类：知识解答、概念解释、事实查询
   - 创意类：文案写作、故事创作、内容生成

4. 识别为深度思考任务（不需要工具，用于复杂推理/分析）：
   - 任务已有所需信息，只需分析和推理
   - 复杂的方案评估、风险分析、比较决策
   - 需要多步骤逻辑推理但不需获取新信息
   - 关键词：分析、评估、比较、推理、计算、推演

可用工具：
{tools}

{history_str}

用户请求：{user_message}

请以 JSON 格式返回执行计划，不要添加任何其他解释：

```json
{{
  "complexity": "SIMPLE|MEDIUM|COMPLEX",
  "strategy": "single|chain|parallel|mixed|thinking",
  "description": "简要描述任务目标和执行思路",
  "steps": [
    {{
      "step_id": "step_1",
      "tool_name": "web_search",
      "arguments": {{"query": "搜索关键词"}},
      "depends_on": []
    }}
  ]
}}
```

重要：steps 中的 tool_name 必须使用上面列出的可用工具之一（如 web_search），不要自己编造工具名。如果不需要工具，返回空数组 steps: []。

重要提示：
1. 如果任务需要获取地点、价格、人气评价等外部信息，必须使用工具策略（single/chain），在steps中定义web_search等工具调用
2. 如果任务已有足够信息需要深度推理分析，使用 strategy: "thinking"，steps 数组为空
3. thinking策略会触发深度思考模式，LLM会完整展示思考过程并制定详细计划（不调用工具）
4. 规划类任务如果需要外部信息（如旅游攻略、餐厅推荐），应先搜索再规划，不要直接用thinking
5. 区分：旅游攻略→先搜索地点信息→再规划路线；商业分析→已有数据→直接thinking
"""

        return prompt

    def _format_tools_for_llm(self, tools: Dict[str, Any]) -> str:
        """Format tools for LLM prompt

        Args:
            tools: Dictionary of tools

        Returns:
            Formatted string
        """
        if not tools:
            return "No tools available"

        descriptions = []
        for tool_name, tool_info in tools.items():
            desc = f"- {tool_name}: {tool_info.get('description', '')}"
            if tool_info.get("input_schema"):
                desc += f"\n  Parameters: {json.dumps(tool_info['input_schema'], indent=2)}"
            descriptions.append(desc)

        return "\n\n".join(descriptions)

    def _parse_llm_response(self, response: str, user_message: str) -> ExecutionPlan:
        """Parse LLM response into execution plan

        Args:
            response: LLM response
            user_message: Original user message

        Returns:
            Execution plan
        """
        try:
            # Extract JSON from response
            json_start = response.find("```json")
            json_end = response.find("```", json_start + 7) if json_start != -1 else -1

            if json_start != -1 and json_end != -1:
                json_str = response[json_start + 7:json_end].strip()
            else:
                # Try to find { and }
                json_start = response.find("{")
                json_end = response.rfind("}")
                if json_start != -1 or json_end == -1:
                    raise ValueError("No JSON found in response")
                json_str = response[json_start:json_end + 1]

            data = json.loads(json_str)

            # Parse complexity
            complexity_str = data.get("complexity", "SIMPLE").upper()
            try:
                complexity = ComplexityLevel(complexity_str)
            except ValueError:
                complexity = ComplexityLevel.SIMPLE

            # Parse strategy
            strategy_str = data.get("strategy", "single").lower()
            try:
                strategy = ExecutionStrategy(strategy_str)
            except ValueError:
                strategy = ExecutionStrategy.SINGLE

            # Parse steps
            steps = []
            for step_data in data.get("steps", []):
                tool_name = step_data.get("tool_name", "")
                # Skip steps with empty tool_name (invalid step)
                if not tool_name:
                    logger.warning(f"Skipping step with empty tool_name: {step_data}")
                    continue
                step = ExecutionStep(
                    step_id=step_data.get("step_id", str(uuid.uuid4())),
                    tool_name=tool_name,
                    arguments=step_data.get("arguments", {}),
                    depends_on=step_data.get("depends_on", []),
                    parallel=step_data.get("parallel", False),
                    retry_on_failure=step_data.get("retry_on_failure", True),
                    max_retries=step_data.get("max_retries", 3)
                )
                steps.append(step)

            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                complexity=complexity,
                strategy=strategy,
                description=data.get("description", user_message),
                steps=steps
            )

        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            # Fallback to simple plan
            return self._create_simple_plan(user_message)

    def _create_simple_plan(self, user_message: str) -> ExecutionPlan:
        """Create simple execution plan (fallback)

        Args:
            user_message: User message

        Returns:
            Simple execution plan
        """
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            complexity=ComplexityLevel.SIMPLE,
            strategy=ExecutionStrategy.SINGLE,
            description=f"处理请求: {user_message[:50]}",
            steps=[]
        )


# Global decision engine instance
decision_engine = ToolDecisionEngine()
