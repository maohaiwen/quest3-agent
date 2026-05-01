# Skill 系统完整设计文档

## 版本信息

| 项目 | 内容 |
|------|------|
| 文档版本 | v1.0 |
| 创建日期 | 2026-04-27 |
| 状态 | 设计中 |

---

## 概述

本文档详细设计 Skill 系统的完整功能，使其从当前的"仅加载"状态变成"完全可用"状态。

---

## 目录

1. [Skill 执行引擎](#1-skill-执行引擎)
2. [Skill 触发机制](#2-skill-触发机制)
3. [Skill 组合和流水线](#3-skill-组合和流水线)
4. [Skill 依赖管理](#4-skill-依赖管理)
5. [Skill 测试调试](#5-skill-测试调试)
6. [Skill 导入分享](#6-skill-导入分享)

---

## 1. Skill 执行引擎

### 1.1 设计目标

- 支持 skill.md 纯提示词模式
- 支持 Python 脚本模式（main.py）
- 支持异步执行
- 上下文管理和数据传递
- 执行状态追踪

### 1.2 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    SkillExecutor                            │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────────┐    ┌─────────────────────────────┐   │
│  │  PromptRunner    │    │      ScriptRunner           │   │
│  │  (纯提示词模式)  │    │     (Python 脚本模式)        │   │
│  └──────────────────┘    └─────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ContextManager                         │   │
│  │         (执行上下文、数据传递、状态追踪)             │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 数据结构

```python
class SkillExecutionContext(BaseModel):
    """Skill 执行上下文"""
    session_id: str                  # 会话 ID
    skill_id: str                    # Skill ID
    skill_name: str                  # Skill 名称
    input_data: Dict[str, Any]       # 输入数据
    config: Dict[str, Any]           # Skill 配置
    state: Dict[str, Any]            # 执行状态（可写）
    tools: List[str]                 # 可用工具
    created_at: datetime

class SkillExecutionResult(BaseModel):
    """Skill 执行结果"""
    success: bool
    output: Any                      # 输出数据
    error: Optional[str]
    execution_time_ms: float
    state_updates: Dict[str, Any]    # 状态更新
    logs: List[str]                  # 执行日志

class SkillExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### 1.4 SkillExecutor 接口

```python
class SkillExecutor:
    """Skill 执行器"""

    def __init__(self, skill_registry: SkillRegistry):
        self.registry = skill_registry
        self.context_manager = SkillContextManager()
        self.runners = {
            "prompt": PromptRunner(),
            "script": ScriptRunner(),
        }

    async def execute(
        self,
        skill_name: str,
        context: SkillExecutionContext,
    ) -> SkillExecutionResult:
        """执行 Skill"""
        skill = self.registry.get_skill(skill_name)
        if not skill:
            return SkillExecutionResult(
                success=False,
                output=None,
                error=f"Skill not found: {skill_name}",
                execution_time_ms=0,
                state_updates={},
                logs=[],
            )

        # 选择 runner
        runner = self._get_runner(skill)

        # 执行
        return await runner.run(skill, context)

    def _get_runner(self, skill: Skill) -> SkillRunner:
        """根据 skill 类型选择 runner"""
        if skill.entrypoint:
            return self.runners["script"]
        return self.runners["prompt"]


class SkillRunner(ABC):
    """Skill Runner 基类"""

    @abstractmethod
    async def run(
        self,
        skill: Skill,
        context: SkillExecutionContext,
    ) -> SkillExecutionResult:
        pass


class PromptRunner(SkillRunner):
    """纯提示词模式 Runner"""

    async def run(
        self,
        skill: Skill,
        context: SkillExecutionContext,
    ) -> SkillExecutionResult:
        """
        纯提示词模式执行：
        1. 将 skill.md 内容注入到系统提示词
        2. 返回增强后的提示词给 LLM
        """
        start_time = time.time()

        try:
            # 构建增强提示词
            enhanced_prompt = self._build_enhanced_prompt(skill, context)

            return SkillExecutionResult(
                success=True,
                output={
                    "type": "prompt_injection",
                    "prompt_content": skill.skill_content,
                    "enhanced_prompt": enhanced_prompt,
                },
                error=None,
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=["Prompt-based skill loaded successfully"],
            )
        except Exception as e:
            return SkillExecutionResult(
                success=False,
                output=None,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=[f"Error: {e}"],
            )

    def _build_enhanced_prompt(
        self,
        skill: Skill,
        context: SkillExecutionContext,
    ) -> str:
        """构建增强提示词"""
        # 将输入数据注入到提示词
        input_str = json.dumps(context.input_data, ensure_ascii=False, indent=2)

        return f"""{skill.skill_content}

【当前上下文】
输入数据:
{input_str}

请根据以上技能说明处理用户请求。
"""


class ScriptRunner(SkillRunner):
    """Python 脚本模式 Runner"""

    async def run(
        self,
        skill: Skill,
        context: SkillExecutionContext,
    ) -> SkillExecutionResult:
        """
        Python 脚本模式执行：
        1. 动态加载 main.py
        2. 调用约定的入口函数
        3. 捕获输出和错误
        """
        start_time = time.time()
        logs = []

        try:
            # 加载模块
            module = await self._load_module(skill)
            logs.append(f"Loaded module from {skill.entrypoint}")

            # 调用入口函数
            if hasattr(module, "execute"):
                # 异步执行
                if inspect.iscoroutinefunction(module.execute):
                    result = await module.execute(context)
                else:
                    result = module.execute(context)
            else:
                # 兼容旧版本，尝试 call 函数
                if hasattr(module, "call"):
                    if inspect.iscoroutinefunction(module.call):
                        result = await module.call(context)
                    else:
                        result = module.call(context)
                else:
                    raise ValueError("Skill module has no 'execute' or 'call' function")

            logs.append("Execution completed successfully")

            # 解析结果
            if isinstance(result, SkillExecutionResult):
                result.logs = logs + result.logs
                result.execution_time_ms = (time.time() - start_time) * 1000
                return result

            return SkillExecutionResult(
                success=True,
                output=result,
                error=None,
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates=getattr(result, "state_updates", {}),
                logs=logs,
            )

        except Exception as e:
            logs.append(f"Error: {e}")
            return SkillExecutionResult(
                success=False,
                output=None,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=logs,
            )

    async def _load_module(self, skill: Skill) -> ModuleType:
        """动态加载 Skill 模块"""
        if not skill.entrypoint:
            raise ValueError("Skill has no entrypoint")

        # 添加 skill 目录到 path
        dir_path = Path(skill.entrypoint).parent
        if str(dir_path) not in sys.path:
            sys.path.insert(0, str(dir_path))

        # 动态导入
        module_name = f"skill_{skill.name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, skill.entrypoint)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module


class SkillContextManager:
    """Skill 上下文管理器"""

    def __init__(self):
        self._contexts: Dict[str, SkillExecutionContext] = {}  # execution_id -> context
        self._states: Dict[str, Dict[str, Any]] = {}  # session_id -> global state

    def create_context(
        self,
        session_id: str,
        skill_name: str,
        input_data: Dict[str, Any],
        config: Dict[str, Any] = None,
    ) -> SkillExecutionContext:
        """创建执行上下文"""
        execution_id = str(uuid.uuid4())

        # 获取或创建会话级状态
        if session_id not in self._states:
            self._states[session_id] = {}

        context = SkillExecutionContext(
            session_id=session_id,
            skill_id=f"skill_{skill_name}",
            skill_name=skill_name,
            input_data=input_data or {},
            config=config or {},
            state=self._states[session_id],
            tools=[],
            created_at=datetime.utcnow(),
        )

        self._contexts[execution_id] = context
        return context

    def get_context(self, execution_id: str) -> Optional[SkillExecutionContext]:
        """获取上下文"""
        return self._contexts.get(execution_id)

    def update_state(
        self,
        session_id: str,
        state_updates: Dict[str, Any],
    ) -> None:
        """更新会话状态"""
        if session_id not in self._states:
            self._states[session_id] = {}
        self._states[session_id].update(state_updates)

    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """获取会话状态"""
        return self._states.get(session_id, {})

    def clear_session(self, session_id: str) -> None:
        """清理会话"""
        if session_id in self._states:
            del self._states[session_id]
        # 同时清理相关的执行上下文
        to_remove = [
            eid for eid, ctx in self._contexts.items()
            if ctx.session_id == session_id
        ]
        for eid in to_remove:
            del self._contexts[eid]
```

### 1.5 Skill 脚本约定

Skill 的 main.py 需要遵循以下约定：

```python
"""Example Skill Script"""
from typing import Any, Dict
from app.models.skill import SkillExecutionContext, SkillExecutionResult

# 方式 1: 简单返回值
def execute(context: SkillExecutionContext) -> Any:
    """
    Skill 入口函数

    Args:
        context: 执行上下文，包含输入、配置、状态

    Returns:
        任意输出数据，或 SkillExecutionResult
    """
    input_data = context.input_data
    config = context.config

    # 读取状态
    counter = context.state.get("counter", 0)

    # 执行业务逻辑
    result = {
        "message": f"Processed: {input_data}",
        "counter": counter + 1,
    }

    # 更新状态
    context.state["counter"] = counter + 1

    return result

# 方式 2: 返回完整结果
async def execute(context: SkillExecutionContext) -> SkillExecutionResult:
    """异步执行，返回完整结果"""
    try:
        # 业务逻辑
        output = do_something(context.input_data)

        return SkillExecutionResult(
            success=True,
            output=output,
            error=None,
            execution_time_ms=0,  # 会被自动填充
            state_updates={"last_run": datetime.utcnow().isoformat()},
            logs=["Processing completed"],
        )
    except Exception as e:
        return SkillExecutionResult(
            success=False,
            output=None,
            error=str(e),
            execution_time_ms=0,
            state_updates={},
            logs=[f"Error: {e}"],
        )
```

---

## 2. Skill 触发机制

### 2.1 设计目标

- 多种触发策略：关键词、意图匹配、正则表达式
- 可配置的自动激活规则
- 支持手动触发和自动触发
- 触发历史和统计

### 2.2 触发策略

```python
class TriggerType(str, Enum):
    """触发类型"""
    KEYWORD = "keyword"          # 关键词匹配
    INTENT = "intent"            # 意图匹配（LLM）
    REGEX = "regex"              # 正则表达式
    ALWAYS = "always"            # 总是触发
    MANUAL = "manual"            # 仅手动触发

class SkillTrigger(BaseModel):
    """Skill 触发规则"""
    id: str
    skill_id: str
    trigger_type: TriggerType
    config: Dict[str, Any]        # 触发配置
    priority: int = 0             # 优先级
    enabled: bool = True
    created_at: datetime

class KeywordTriggerConfig(BaseModel):
    """关键词触发配置"""
    keywords: List[str]           # 关键词列表
    case_sensitive: bool = False  # 大小写敏感
    match_all: bool = False       # 需要匹配所有关键词

class RegexTriggerConfig(BaseModel):
    """正则触发配置"""
    pattern: str                  # 正则表达式
    flags: List[str] = []         # 正则 flags

class IntentTriggerConfig(BaseModel):
    """意图触发配置"""
    intent_description: str       # 意图描述
    confidence_threshold: float = 0.7  # 置信度阈值
```

### 2.3 SkillTriggerManager

```python
class SkillTriggerManager:
    """Skill 触发管理器"""

    def __init__(self, skill_registry: SkillRegistry):
        self.registry = skill_registry
        self._triggers: Dict[str, SkillTrigger] = {}  # trigger_id -> trigger
        self._skill_triggers: Dict[str, List[str]] = {}  # skill_id -> [trigger_ids]

    def add_trigger(self, trigger: SkillTrigger) -> None:
        """添加触发规则"""
        self._triggers[trigger.id] = trigger
        if trigger.skill_id not in self._skill_triggers:
            self._skill_triggers[trigger.skill_id] = []
        self._skill_triggers[trigger.skill_id].append(trigger.id)

    def remove_trigger(self, trigger_id: str) -> bool:
        """移除触发规则"""
        trigger = self._triggers.pop(trigger_id, None)
        if trigger and trigger.skill_id in self._skill_triggers:
            self._skill_triggers[trigger.skill_id].remove(trigger_id)
        return trigger is not None

    def get_triggers_for_skill(self, skill_id: str) -> List[SkillTrigger]:
        """获取 skill 的所有触发规则"""
        trigger_ids = self._skill_triggers.get(skill_id, [])
        return [self._triggers[tid] for tid in trigger_ids if tid in self._triggers]

    async def find_matching_skills(
        self,
        message: str,
        session_id: str = None,
    ) -> List[Tuple[Skill, float]]:
        """
        查找匹配的 Skills

        Args:
            message: 用户消息
            session_id: 会话 ID

        Returns:
            List of (Skill, confidence) tuples, sorted by confidence and priority
        """
        matches = []

        for trigger in self._triggers.values():
            if not trigger.enabled:
                continue

            confidence = await self._check_trigger(trigger, message)
            if confidence > 0:
                skill = self.registry.get_skill_by_id(trigger.skill_id)
                if skill and skill.enabled:
                    matches.append((skill, confidence, trigger.priority))

        # 排序：先按优先级，再按置信度
        matches.sort(key=lambda x: (-x[2], -x[1]))

        return [(skill, conf) for skill, conf, _ in matches]

    async def _check_trigger(
        self,
        trigger: SkillTrigger,
        message: str,
    ) -> float:
        """检查触发是否匹配，返回置信度 (0-1)"""
        if trigger.trigger_type == TriggerType.KEYWORD:
            return await self._check_keyword_trigger(trigger, message)
        elif trigger.trigger_type == TriggerType.REGEX:
            return await self._check_regex_trigger(trigger, message)
        elif trigger.trigger_type == TriggerType.INTENT:
            return await self._check_intent_trigger(trigger, message)
        elif trigger.trigger_type == TriggerType.ALWAYS:
            return 1.0
        elif trigger.trigger_type == TriggerType.MANUAL:
            return 0.0
        else:
            return 0.0

    async def _check_keyword_trigger(
        self,
        trigger: SkillTrigger,
        message: str,
    ) -> float:
        """关键词匹配"""
        config = KeywordTriggerConfig(**trigger.config)
        message_lower = message.lower() if not config.case_sensitive else message

        matched_count = 0
        for keyword in config.keywords:
            kw = keyword.lower() if not config.case_sensitive else keyword
            if kw in message_lower:
                matched_count += 1

        if config.match_all:
            return 1.0 if matched_count == len(config.keywords) else 0.0
        else:
            return matched_count / len(config.keywords) if config.keywords else 0.0

    async def _check_regex_trigger(
        self,
        trigger: SkillTrigger,
        message: str,
    ) -> float:
        """正则匹配"""
        config = RegexTriggerConfig(**trigger.config)

        flags = 0
        for flag_str in config.flags:
            if hasattr(re, flag_str.upper()):
                flags |= getattr(re, flag_str.upper())

        if re.search(config.pattern, message, flags):
            return 1.0
        return 0.0

    async def _check_intent_trigger(
        self,
        trigger: SkillTrigger,
        message: str,
    ) -> float:
        """意图匹配（使用 LLM）"""
        config = IntentTriggerConfig(**trigger.config)

        # 使用 LLM 判断意图匹配度
        prompt = f"""请判断用户消息是否匹配以下意图。

意图描述: {config.intent_description}

用户消息: {message}

请返回 0 到 1 之间的数字，表示匹配程度（1 表示完全匹配，0 表示完全不匹配）。
只返回数字，不要其他内容。"""

        try:
            # 调用 LLM 获取匹配度
            # 这里假设我们有一个 llm_service
            # result = await llm_service.complete(prompt)
            # confidence = float(result.strip())
            # return max(0.0, min(1.0, confidence))

            # 临时返回 0，需要集成 LLM 服务
            return 0.0
        except Exception:
            return 0.0
```

### 2.4 触发配置示例

在 skill.md 的 frontmatter 中可以定义触发规则：

```yaml
---
name: code_reviewer
version: 1.0.0
description: 代码审查助手
triggers:
  - type: keyword
    keywords: ["review", "代码审查", "检查代码", "code review"]
    priority: 10
  - type: intent
    intent_description: "用户想要审查、检查或改进代码质量"
    priority: 5
---
```

---

## 3. Skill 组合和流水线

### 3.1 设计目标

- Skill 之间的数据传递
- 顺序执行（Pipeline）
- 并行执行（Fork/Join）
- 条件分支
- Skill 依赖声明

### 3.2 数据结构

```python
class SkillPipelineStep(BaseModel):
    """流水线步骤"""
    step_id: str
    skill_name: str
    input_mapping: Dict[str, str] = Field(default_factory=dict)  # 输入映射: 目标字段 -> 源路径
    output_mapping: Dict[str, str] = Field(default_factory=dict)  # 输出映射: 源路径 -> 目标字段
    condition: Optional[str] = None  # 条件表达式
    parallel: bool = False  # 是否并行执行
    depends_on: List[str] = Field(default_factory=list)  # 依赖的步骤

class SkillPipeline(BaseModel):
    """Skill 流水线"""
    id: str
    name: str
    description: str
    steps: List[SkillPipelineStep]
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    version: str = "1.0.0"

class PipelineExecutionState(BaseModel):
    """流水线执行状态"""
    pipeline_id: str
    execution_id: str
    current_step: Optional[str]
    step_results: Dict[str, SkillExecutionResult]
    completed: bool
    success: bool
    error: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
```

### 3.3 PipelineExecutor

```python
class PipelineExecutor:
    """流水线执行器"""

    def __init__(self, skill_executor: SkillExecutor):
        self.skill_executor = skill_executor
        self._states: Dict[str, PipelineExecutionState] = {}

    async def execute(
        self,
        pipeline: SkillPipeline,
        input_data: Dict[str, Any],
        session_id: str = None,
    ) -> PipelineExecutionState:
        """执行流水线"""
        execution_id = str(uuid.uuid4())
        state = PipelineExecutionState(
            pipeline_id=pipeline.id,
            execution_id=execution_id,
            current_step=None,
            step_results={},
            completed=False,
            success=False,
            error=None,
            started_at=datetime.utcnow(),
            completed_at=None,
        )
        self._states[execution_id] = state

        try:
            # 拓扑排序步骤
            sorted_steps = self._topological_sort(pipeline.steps)

            # 按组执行（并行组）
            for step_group in self._group_steps(sorted_steps):
                await self._execute_step_group(
                    step_group,
                    pipeline,
                    input_data,
                    state,
                    session_id,
                )
                if state.error:
                    break

            state.success = state.error is None
            state.completed = True
            state.completed_at = datetime.utcnow()

        except Exception as e:
            state.error = str(e)
            state.completed = True
            state.completed_at = datetime.utcnow()

        return state

    def _topological_sort(
        self,
        steps: List[SkillPipelineStep],
    ) -> List[SkillPipelineStep]:
        """拓扑排序"""
        # 实现 Kahn's 算法
        step_map = {s.step_id: s for s in steps}
        in_degree = {s.step_id: 0 for s in steps}

        for step in steps:
            for dep_id in step.depends_on:
                in_degree[step.step_id] += 1

        queue = deque([s for s in steps if in_degree[s.step_id] == 0])
        result = []

        while queue:
            step = queue.popleft()
            result.append(step)

            # 查找依赖此步骤的步骤
            for other_step in steps:
                if step.step_id in other_step.depends_on:
                    in_degree[other_step.step_id] -= 1
                    if in_degree[other_step.step_id] == 0:
                        queue.append(other_step)

        if len(result) != len(steps):
            raise ValueError("Pipeline has circular dependency")

        return result

    def _group_steps(
        self,
        sorted_steps: List[SkillPipelineStep],
    ) -> List[List[SkillPipelineStep]]:
        """将步骤分组，并行的步骤在同一组"""
        groups = []
        current_group = []

        for step in sorted_steps:
            if step.parallel and current_group:
                # 继续当前并行组
                current_group.append(step)
            elif step.parallel:
                # 开始新并行组
                current_group = [step]
            else:
                if current_group:
                    # 结束并行组
                    groups.append(current_group)
                    current_group = []
                # 串行步骤单独一组
                groups.append([step])

        if current_group:
            groups.append(current_group)

        return groups

    async def _execute_step_group(
        self,
        step_group: List[SkillPipelineStep],
        pipeline: SkillPipeline,
        input_data: Dict[str, Any],
        state: PipelineExecutionState,
        session_id: str,
    ) -> None:
        """执行一组步骤"""
        if len(step_group) == 1:
            # 串行执行
            step = step_group[0]
            await self._execute_step(step, pipeline, input_data, state, session_id)
        else:
            # 并行执行
            await asyncio.gather(*[
                self._execute_step(step, pipeline, input_data, state, session_id)
                for step in step_group
            ])

    async def _execute_step(
        self,
        step: SkillPipelineStep,
        pipeline: SkillPipeline,
        input_data: Dict[str, Any],
        state: PipelineExecutionState,
        session_id: str,
    ) -> None:
        """执行单个步骤"""
        # 检查条件
        if step.condition:
            if not self._evaluate_condition(step.condition, input_data, state):
                return  # 跳过此步骤

        # 构建输入
        step_input = self._build_step_input(step, input_data, state)

        # 执行 skill
        context = self.skill_executor.context_manager.create_context(
            session_id=session_id or state.execution_id,
            skill_name=step.skill_name,
            input_data=step_input,
        )

        result = await self.skill_executor.execute(step.skill_name, context)

        # 保存结果
        state.step_results[step.step_id] = result

        if not result.success:
            state.error = f"Step {step.step_id} failed: {result.error}"

        # 映射输出
        self._map_step_output(step, result, input_data, state)

    def _build_step_input(
        self,
        step: SkillPipelineStep,
        pipeline_input: Dict[str, Any],
        state: PipelineExecutionState,
    ) -> Dict[str, Any]:
        """构建步骤输入"""
        step_input = {}

        for target_field, source_path in step.input_mapping.items():
            value = self._resolve_path(source_path, pipeline_input, state)
            # 设置嵌套字段
            self._set_nested_field(step_input, target_field, value)

        # 如果没有映射，使用完整输入
        if not step.input_mapping:
            step_input = pipeline_input.copy()

        return step_input

    def _map_step_output(
        self,
        step: SkillPipelineStep,
        result: SkillExecutionResult,
        pipeline_input: Dict[str, Any],
        state: PipelineExecutionState,
    ) -> None:
        """映射步骤输出"""
        for source_path, target_field in step.output_mapping.items():
            value = self._resolve_path(source_path, {"output": result.output}, state)
            self._set_nested_field(pipeline_input, target_field, value)

    def _resolve_path(
        self,
        path: str,
        data: Dict[str, Any],
        state: PipelineExecutionState,
    ) -> Any:
        """解析数据路径

        支持的路径格式:
        - $.field  - pipeline 输入
        - $.step1.output.field  - 步骤输出
        - $.step2.state.counter - 步骤状态
        """
        if path.startswith("$."):
            path = path[2:]

        parts = path.split(".")

        # 检查是否引用步骤
        if parts[0] in state.step_results:
            step_id = parts[0]
            step_result = state.step_results[step_id]

            if parts[1] == "output":
                current = step_result.output
            elif parts[1] == "state":
                # 从上下文获取状态
                # 这里简化处理
                current = {}
            else:
                current = step_result.output

            parts = parts[2:]
        else:
            current = data

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                current = current[int(part)] if part.isdigit() else None
            else:
                return None
            if current is None:
                break

        return current

    def _set_nested_field(
        self,
        data: Dict[str, Any],
        path: str,
        value: Any,
    ) -> None:
        """设置嵌套字段"""
        parts = path.split(".")
        current = data

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    def _evaluate_condition(
        self,
        condition: str,
        data: Dict[str, Any],
        state: PipelineExecutionState,
    ) -> bool:
        """评估条件表达式"""
        # 简单的条件评估
        # 安全考虑，使用受限的 eval 或实现简单的表达式解析器
        try:
            # 这里简化处理，实际应该用安全的表达式引擎
            namespace = {
                "input": data,
                "results": {
                    step_id: result.output
                    for step_id, result in state.step_results.items()
                },
            }
            return bool(eval(condition, {"__builtins__": {}}, namespace))
        except Exception:
            return False
```

### 3.4 流水线定义示例

可以用 YAML 定义流水线：

```yaml
id: code_analysis_pipeline
name: 代码分析流水线
description: 先审查代码，再生成文档
steps:
  - step_id: review
    skill_name: code_reviewer
    input_mapping:
      code: $.code
    output_mapping:
      $.output.issues: issues
      $.output.summary: review_summary

  - step_id: document
    skill_name: doc_generator
    depends_on: ["review"]
    input_mapping:
      code: $.code
      issues: $.issues
      summary: $.review_summary
    output_mapping:
      $.output.document: final_document
```

---

## 4. Skill 依赖管理

### 4.1 设计目标

- 自动安装 requirements
- Skill 隔离环境（可选）
- 版本兼容性检查
- 依赖缓存

### 4.2 数据结构

```python
class SkillDependency(BaseModel):
    """Skill 依赖"""
    name: str
    version_spec: Optional[str] = None  # e.g., ">=1.0.0,<2.0.0"
    required: bool = True

class SkillEnvironment(BaseModel):
    """Skill 环境"""
    skill_id: str
    env_path: str
    dependencies: List[SkillDependency]
    created_at: datetime
    last_used: datetime
```

### 4.3 DependencyManager

```python
class DependencyManager:
    """Skill 依赖管理器"""

    def __init__(self, base_env_path: str = None):
        self.base_env_path = Path(base_env_path) if base_env_path else Path.home() / ".quest3" / "envs"
        self.base_env_path.mkdir(parents=True, exist_ok=True)
        self._environments: Dict[str, SkillEnvironment] = {}

    async def install_dependencies(
        self,
        skill: Skill,
        isolate: bool = False,
    ) -> bool:
        """
        安装 Skill 依赖

        Args:
            skill: Skill 对象
            isolate: 是否使用隔离环境

        Returns:
            是否成功
        """
        if not skill.requirements:
            return True

        logger.info(f"Installing dependencies for {skill.name}: {skill.requirements}")

        if isolate:
            return await self._install_isolated(skill)
        else:
            return await self._install_global(skill)

    async def _install_global(self, skill: Skill) -> bool:
        """全局安装依赖"""
        try:
            for req in skill.requirements:
                await self._pip_install(req)
            return True
        except Exception as e:
            logger.error(f"Failed to install dependencies: {e}")
            return False

    async def _install_isolated(self, skill: Skill) -> bool:
        """在隔离环境中安装"""
        env_path = self.base_env_path / skill.name

        # 创建虚拟环境
        if not env_path.exists():
            await self._create_virtualenv(env_path)

        # 安装依赖
        pip_path = env_path / "bin" / "pip" if sys.platform != "win32" else env_path / "Scripts" / "pip.exe"

        try:
            for req in skill.requirements:
                await self._pip_install(req, pip_path=str(pip_path))

            # 保存环境信息
            self._environments[skill.id] = SkillEnvironment(
                skill_id=skill.id,
                env_path=str(env_path),
                dependencies=[],  # TODO: 解析 requirements
                created_at=datetime.utcnow(),
                last_used=datetime.utcnow(),
            )

            return True
        except Exception as e:
            logger.error(f"Failed to install in isolated env: {e}")
            return False

    async def _create_virtualenv(self, env_path: Path) -> None:
        """创建虚拟环境"""
        import venv
        venv.create(env_path, with_pip=True)

        # 升级 pip
        pip_path = env_path / "bin" / "pip" if sys.platform != "win32" else env_path / "Scripts" / "pip.exe"
        await self._pip_install("--upgrade pip", pip_path=str(pip_path))

    async def _pip_install(self, requirement: str, pip_path: str = "pip") -> None:
        """执行 pip install"""
        import subprocess

        cmd = [pip_path, "install", requirement]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"pip install failed: {error}")

    def get_environment(self, skill_id: str) -> Optional[SkillEnvironment]:
        """获取 Skill 的环境"""
        return self._environments.get(skill_id)

    async def check_compatibility(self, skill: Skill) -> Tuple[bool, List[str]]:
        """
        检查依赖兼容性

        Returns:
            (是否兼容, 问题列表)
        """
        issues = []

        for req_str in skill.requirements:
            # 解析 requirement
            req = self._parse_requirement(req_str)

            # 检查已安装版本
            try:
                installed = importlib.metadata.version(req.name)
                if req.version_spec and not self._version_match(installed, req.version_spec):
                    issues.append(
                        f"{req.name}: installed {installed}, requires {req.version_spec}"
                    )
            except importlib.metadata.PackageNotFoundError:
                issues.append(f"{req.name}: not installed")

        return len(issues) == 0, issues

    def _parse_requirement(self, req_str: str) -> SkillDependency:
        """解析 requirement 字符串"""
        # 简单解析，实际可以用 packaging 库
        import re

        match = re.match(r"([a-zA-Z0-9_-]+)(.*)", req_str)
        if match:
            name = match.group(1)
            version_spec = match.group(2).strip() if match.group(2) else None
            return SkillDependency(name=name, version_spec=version_spec)

        return SkillDependency(name=req_str)

    def _version_match(self, version: str, spec: str) -> bool:
        """检查版本匹配"""
        # 使用 packaging 库
        try:
            from packaging import version as pkg_version
            from packaging.specifiers import SpecifierSet

            ver = pkg_version.parse(version)
            spec_set = SpecifierSet(spec)
            return ver in spec_set
        except Exception:
            return False  # 保守处理
```

---

## 5. Skill 测试调试

### 5.1 设计目标

- Skill 单元测试框架
- 执行日志记录
- 调试模式支持
- 执行回放

### 5.2 数据结构

```python
class SkillTestSpec(BaseModel):
    """Skill 测试用例"""
    name: str
    description: str
    input_data: Dict[str, Any]
    expected_output: Optional[Dict[str, Any]] = None
    expected_state: Optional[Dict[str, Any]] = None
    expected_to_fail: bool = False

class SkillTestResult(BaseModel):
    """Skill 测试结果"""
    test_name: str
    success: bool
    passed: bool
    error: Optional[str]
    actual_output: Any
    expected_output: Any
    execution_time_ms: float
    logs: List[str]

class SkillExecutionLog(BaseModel):
    """Skill 执行日志"""
    execution_id: str
    skill_name: str
    session_id: Optional[str]
    timestamp: datetime
    level: str  # debug, info, warning, error
    message: str
    data: Optional[Dict[str, Any]] = None
```

### 5.3 SkillTester

```python
class SkillTester:
    """Skill 测试器"""

    def __init__(self, skill_executor: SkillExecutor):
        self.executor = skill_executor
        self._logs: List[SkillExecutionLog] = []

    async def run_tests(
        self,
        skill_name: str,
        tests: List[SkillTestSpec],
    ) -> List[SkillTestResult]:
        """运行测试用例"""
        results = []

        for test in tests:
            result = await self._run_test(skill_name, test)
            results.append(result)

        return results

    async def _run_test(
        self,
        skill_name: str,
        test: SkillTestSpec,
    ) -> SkillTestResult:
        """运行单个测试"""
        start_time = time.time()
        logs = []

        try:
            # 创建测试会话
            test_session_id = f"test_{uuid.uuid4()}"

            # 执行 skill
            context = self.executor.context_manager.create_context(
                session_id=test_session_id,
                skill_name=skill_name,
                input_data=test.input_data,
            )

            exec_result = await self.executor.execute(skill_name, context)

            logs.extend(exec_result.logs)

            # 检查结果
            passed = self._check_result(test, exec_result)

            return SkillTestResult(
                test_name=test.name,
                success=exec_result.success,
                passed=passed,
                error=exec_result.error,
                actual_output=exec_result.output,
                expected_output=test.expected_output,
                execution_time_ms=(time.time() - start_time) * 1000,
                logs=logs,
            )

        except Exception as e:
            return SkillTestResult(
                test_name=test.name,
                success=False,
                passed=False,
                error=str(e),
                actual_output=None,
                expected_output=test.expected_output,
                execution_time_ms=(time.time() - start_time) * 1000,
                logs=logs + [f"Exception: {e}"],
            )

    def _check_result(
        self,
        test: SkillTestSpec,
        exec_result: SkillExecutionResult,
    ) -> bool:
        """检查测试结果"""
        if test.expected_to_fail:
            return not exec_result.success

        if not exec_result.success:
            return False

        if test.expected_output:
            # 深度比较
            return self._deep_equal(exec_result.output, test.expected_output)

        return True

    def _deep_equal(self, a: Any, b: Any) -> bool:
        """深度比较"""
        if type(a) != type(b):
            return False

        if isinstance(a, dict):
            if a.keys() != b.keys():
                return False
            return all(self._deep_equal(a[k], b[k]) for k in a)

        if isinstance(a, list):
            if len(a) != len(b):
                return False
            return all(self._deep_equal(x, y) for x, y in zip(a, b))

        return a == b

    def load_tests_from_file(self, test_file: Path) -> List[SkillTestSpec]:
        """从文件加载测试用例"""
        # 支持 YAML/JSON 格式
        content = test_file.read_text()

        if test_file.suffix in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(content)
        else:
            import json
            data = json.loads(content)

        return [SkillTestSpec(**t) for t in data.get("tests", [])]


class SkillDebugger:
    """Skill 调试器"""

    def __init__(self):
        self._breakpoints: Set[str] = set()
        self._execution_traces: Dict[str, List[Dict[str, Any]]] = {}

    def set_breakpoint(self, skill_name: str, location: str = None) -> None:
        """设置断点"""
        bp_id = f"{skill_name}:{location or '*'}"
        self._breakpoints.add(bp_id)

    def clear_breakpoint(self, skill_name: str, location: str = None) -> None:
        """清除断点"""
        bp_id = f"{skill_name}:{location or '*'}"
        self._breakpoints.discard(bp_id)

    async def debug_execute(
        self,
        executor: SkillExecutor,
        skill_name: str,
        input_data: Dict[str, Any],
        on_breakpoint: Callable[[str, Dict[str, Any]], Awaitable[bool]] = None,
    ) -> SkillExecutionResult:
        """调试执行"""
        execution_id = str(uuid.uuid4())
        trace = []
        self._execution_traces[execution_id] = trace

        # 包装 context 来追踪状态变化
        # 这里简化处理

        # 执行
        context = executor.context_manager.create_context(
            session_id=f"debug_{execution_id}",
            skill_name=skill_name,
            input_data=input_data,
        )

        result = await executor.execute(skill_name, context)

        # 保存追踪信息
        trace.append({
            "type": "execution_complete",
            "result": result,
        })

        return result

    def get_trace(self, execution_id: str) -> Optional[List[Dict[str, Any]]]:
        """获取执行追踪"""
        return self._execution_traces.get(execution_id)
```

### 5.4 测试用例示例

可以在 skill 目录下创建 tests.yaml：

```yaml
tests:
  - name: simple_review
    description: 简单代码审查测试
    input_data:
      code: |
        def add(a, b):
            return a + b
    expected_output:
      issues: []
      score: 10

  - name: bad_code
    description: 有问题的代码
    input_data:
      code: |
        def foo(x):
            for i in range(10):
                if x:
                    return i
            # no return
    expected_output:
      issues:
        - type: "missing_return"
          message: "Not all paths return a value"
```

---

## 6. Skill 导入分享

### 6.1 设计目标

- 从 GitHub 导入
- 从 Gist 导入
- 从 URL 导入
- Skill 打包和导出
- Skill 元数据验证

### 6.2 数据结构

```python
class SkillImportSource(str, Enum):
    """导入来源"""
    GITHUB = "github"
    GIST = "gist"
    URL = "url"
    FILE = "file"
    ARCHIVE = "archive"  # zip/tar.gz

class SkillImportSpec(BaseModel):
    """导入规格"""
    source: SkillImportSource
    location: str          # URL, repo, path 等
    ref: Optional[str] = None  # branch, tag, commit
    subpath: Optional[str] = None  # 子路径
    config: Dict[str, Any] = Field(default_factory=dict)

class SkillPackage(BaseModel):
    """Skill 包"""
    name: str
    version: str
    description: str
    author: Optional[str]
    skill_content: str
    requirements: List[str]
    tags: List[str]
    tools: List[str]
    files: Dict[str, str]  # filename -> content
    created_at: datetime
```

### 6.3 SkillImporter

```python
class SkillImporter:
    """Skill 导入器"""

    def __init__(self, skill_registry: SkillRegistry, user_skills_dir: Path):
        self.registry = skill_registry
        self.user_skills_dir = user_skills_dir
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)

    async def import_skill(self, spec: SkillImportSpec) -> Skill:
        """导入 Skill"""
        if spec.source == SkillImportSource.GITHUB:
            return await self._import_from_github(spec)
        elif spec.source == SkillImportSource.GIST:
            return await self._import_from_gist(spec)
        elif spec.source == SkillImportSource.URL:
            return await self._import_from_url(spec)
        elif spec.source == SkillImportSource.FILE:
            return await self._import_from_file(spec)
        elif spec.source == SkillImportSource.ARCHIVE:
            return await self._import_from_archive(spec)
        else:
            raise ValueError(f"Unsupported source: {spec.source}")

    async def _import_from_github(self, spec: SkillImportSpec) -> Skill:
        """从 GitHub 导入"""
        # 解析 repo 格式: owner/repo
        parts = spec.location.split("/")
        if len(parts) < 2:
            raise ValueError("Invalid GitHub repo format, use owner/repo")

        owner, repo = parts[0], parts[1]

        # 构建 API URL
        ref = spec.ref or "main"
        subpath = spec.subpath or ""

        # 使用 GitHub API 获取内容
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{subpath}"
        if ref:
            api_url += f"?ref={ref}"

        # 下载文件
        files = await self._download_github_directory(api_url)

        # 保存到本地
        skill_dir = self.user_skills_dir / repo
        skill_dir.mkdir(exist_ok=True)

        for filename, content in files.items():
            (skill_dir / filename).write_text(content, encoding="utf-8")

        # 加载 skill
        self.registry.reload()
        skill = self.registry.get_skill(repo)

        if not skill:
            raise ValueError("Failed to load imported skill")

        return skill

    async def _download_github_directory(self, api_url: str) -> Dict[str, str]:
        """下载 GitHub 目录内容"""
        import httpx

        files = {}

        async with httpx.AsyncClient() as client:
            response = await client.get(api_url)
            response.raise_for_status()
            items = response.json()

            for item in items:
                if item["type"] == "file":
                    file_response = await client.get(item["download_url"])
                    files[item["name"]] = file_response.text
                elif item["type"] == "dir":
                    # 递归下载
                    sub_files = await self._download_github_directory(item["url"])
                    files.update({f"{item['name']}/{k}": v for k, v in sub_files.items()})

        return files

    async def _import_from_gist(self, spec: SkillImportSpec) -> Skill:
        """从 Gist 导入"""
        import httpx

        # Gist ID 是 location 的最后部分
        gist_id = spec.location.split("/")[-1]

        api_url = f"https://api.github.com/gists/{gist_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(api_url)
            response.raise_for_status()
            gist_data = response.json()

        # 创建 skill 目录
        gist_name = gist_data.get("description", f"gist_{gist_id}")[:50]
        skill_dir = self.user_skills_dir / self._sanitize_name(gist_name)
        skill_dir.mkdir(exist_ok=True)

        # 保存文件
        for filename, file_data in gist_data["files"].items():
            content = file_data["content"]
            (skill_dir / filename).write_text(content, encoding="utf-8")

        # 加载
        self.registry.reload()
        skill = self.registry.get_skill(self._sanitize_name(gist_name))

        if not skill:
            # 尝试查找第一个包含 skill.md 的目录
            raise ValueError("Failed to load imported skill")

        return skill

    async def _import_from_url(self, spec: SkillImportSpec) -> Skill:
        """从 URL 导入"""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(spec.location)
            response.raise_for_status()

        # 判断内容类型
        content_type = response.headers.get("content-type", "")

        if "zip" in content_type or spec.location.endswith(".zip"):
            # 处理 zip
            return await self._import_from_zip_content(response.content)
        elif spec.location.endswith(".md"):
            # 单个 skill.md
            return await self._import_single_skill_md(response.text)
        else:
            # 尝试解析为目录列表
            raise ValueError("Unsupported URL content")

    async def _import_from_file(self, spec: SkillImportSpec) -> Skill:
        """从本地文件导入"""
        path = Path(spec.location)

        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        if path.is_file():
            if path.suffix == ".md":
                return await self._import_single_skill_md(path.read_text(encoding="utf-8"))
            elif path.suffix in (".zip", ".tar.gz"):
                return await self._import_from_archive(spec)
        else:
            # 目录 - 复制
            import shutil
            dest_dir = self.user_skills_dir / path.name
            shutil.copytree(path, dest_dir, dirs_exist_ok=True)

            self.registry.reload()
            skill = self.registry.get_skill(path.name)
            if not skill:
                raise ValueError("Failed to load imported skill")
            return skill

        raise ValueError("Unsupported file type")

    async def _import_from_archive(self, spec: SkillImportSpec) -> Skill:
        """从压缩包导入"""
        import shutil
        import tempfile

        path = Path(spec.location)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            if path.suffix == ".zip":
                import zipfile
                with zipfile.ZipFile(path, "r") as zip_ref:
                    zip_ref.extractall(temp_path)
            elif path.suffix == ".tar.gz":
                import tarfile
                with tarfile.open(path, "r:gz") as tar_ref:
                    tar_ref.extractall(temp_path)

            # 查找 skill.md
            skill_md_files = list(temp_path.rglob("skill.md"))

            if not skill_md_files:
                raise ValueError("No skill.md found in archive")

            # 取第一个
            skill_dir = skill_md_files[0].parent

            # 复制到 user_skills
            dest_name = skill_dir.name
            dest_dir = self.user_skills_dir / dest_name

            shutil.copytree(skill_dir, dest_dir, dirs_exist_ok=True)

            self.registry.reload()
            skill = self.registry.get_skill(dest_name)
            if not skill:
                raise ValueError("Failed to load imported skill")
            return skill

    async def _import_single_skill_md(self, content: str) -> Skill:
        """导入单个 skill.md"""
        # 解析名称
        import re

        match = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
        if match:
            name = match.group(1).strip()
        else:
            name = f"skill_{uuid.uuid4().hex[:8]}"

        name = self._sanitize_name(name)

        skill_dir = self.user_skills_dir / name
        skill_dir.mkdir(exist_ok=True)
        (skill_dir / "skill.md").write_text(content, encoding="utf-8")

        self.registry.reload()
        skill = self.registry.get_skill(name)

        if not skill:
            raise ValueError("Failed to load imported skill")

        return skill

    async def _import_from_zip_content(self, content: bytes) -> Skill:
        """从 zip 内容导入"""
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "import.zip"
            zip_path.write_bytes(content)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_path)

            # 查找 skill.md
            skill_md_files = list(temp_path.rglob("skill.md"))

            if not skill_md_files:
                raise ValueError("No skill.md found in zip")

            skill_dir = skill_md_files[0].parent
            dest_name = skill_dir.name
            dest_dir = self.user_skills_dir / dest_name

            import shutil
            shutil.copytree(skill_dir, dest_dir, dirs_exist_ok=True)

            self.registry.reload()
            skill = self.registry.get_skill(dest_name)
            if not skill:
                raise ValueError("Failed to load imported skill")
            return skill

    def _sanitize_name(self, name: str) -> str:
        """清理名称"""
        import re
        return re.sub(r"[^a-zA-Z0-9_-]", "_", name)

    async def export_skill(self, skill_name: str, output_path: Path) -> None:
        """导出 Skill"""
        skill = self.registry.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill not found: {skill_name}")

        if not skill.dir_path:
            raise ValueError("Skill has no directory, cannot export")

        skill_dir = Path(skill.dir_path)

        # 创建 zip
        import zipfile

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in skill_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(skill_dir.parent)
                    zipf.write(file_path, arcname)

    async def search_skills(
        self,
        query: str,
        source: Optional[SkillImportSource] = None,
    ) -> List[Dict[str, Any]]:
        """搜索可用的 Skills（示例实现）"""
        # 可以从 GitHub 搜索、skill registry 等
        # 这里返回空列表
        return []

    def validate_skill_package(self, package: SkillPackage) -> Tuple[bool, List[str]]:
        """
        验证 Skill 包

        Returns:
            (是否有效, 问题列表)
        """
        issues = []

        if not package.name:
            issues.append("Name is required")

        if not package.skill_content:
            issues.append("Skill content is required")

        # 解析并验证 skill.md
        try:
            loader = SkillLoader()
            loader.load_skill_from_string(package.name, package.skill_content)
        except Exception as e:
            issues.append(f"Invalid skill.md: {e}")

        return len(issues) == 0, issues

    def _sanitize_name(self, name: str) -> str:
        """清理文件名"""
        import re
        return re.sub(r'[<>:"/\\|?*]', '_', name)
```

---

## 总结

以上设计涵盖了：

1. ✅ **Skill 执行引擎** - PromptRunner 和 ScriptRunner
2. ✅ **Skill 触发机制** - 关键词、意图、正则触发
3. ✅ **Skill 组合和流水线** - PipelineExecutor 支持顺序/并行/条件
4. ✅ **Skill 依赖管理** - DependencyManager 支持隔离环境
5. ✅ **Skill 测试调试** - SkillTester 和 SkillDebugger
6. ✅ **Skill 导入分享** - GitHub/Gist/URL/文件导入

接下来我们可以逐步实现这些模块。
