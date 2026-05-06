# Quest3 Agent 多智能体协作平台 - 深度学习指南

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈详解](#2-技术栈详解)
3. [系统架构总览](#3-系统架构总览)
4. [核心模块详解](#4-核心模块详解)
5. [Agent 智能体系统](#5-agent-智能体系统)
6. [执行引擎与策略路由](#6-执行引擎与策略路由)
7. [统一工具管理系统](#7-统一工具管理系统)
8. [MCP 服务器与客户端池](#8-mcp-服务器与客户端池)
9. [技能系统 (Skill System)](#9-技能系统-skill-system)
10. [多智能体协作](#10-多智能体协作)
11. [A2A 协议与 Agent 注册中心](#11-a2a-协议与-agent-注册中心)
12. [记忆系统](#12-记忆系统)
13. [LLM 服务层](#13-llm-服务层)
14. [API 层设计](#14-api-层设计)
15. [数据层设计](#15-数据层设计)
16. [配置与热更新](#16-配置与热更新)
17. [关键技术点深入](#17-关键技术点深入)
18. [设计模式应用](#18-设计模式应用)
19. [异步编程深入](#19-异步编程深入)
20. [部署与扩展](#20-部署与扩展)

---

## 1. 项目概述

### 什么是多智能体协作平台？

Quest3 Agent 是一个基于 FastAPI 和火山引擎（Volcengine）LLM 的**多智能体协作平台**，远超简单的聊天机器人，具备以下核心能力：

- **多执行模式**：直接对话、规划执行、ReAct 循环、ReAct + 思维链
- **多智能体协作**：监督者模式、流水线模式、投票模式、对抗博弈模式
- **工具集成**：本地工具 + MCP 远程工具 + 技能工具，统一管理
- **长期记忆**：Agent 级记忆提取、语义搜索、重要性衰减
- **技能系统**：内置/用户/缓存技能，支持 GitHub 导入和脚本执行
- **深度思考**：基于火山引擎深度思考 API 的流式推理
- **A2A 协议**：Agent-to-Agent 标准化通信

### 项目特色

1. **全异步架构**：async/await 实现高并发，WebSocket 流式响应
2. **模块化设计**：执行器、工具管理器、协作引擎均可独立扩展
3. **统一工具管理**：本地/MCP/技能工具通过 UnifiedToolManager 统一调度
4. **灵活的 Agent 配置**：每个 Agent 独立配置模型、工具、MCP 服务器、技能
5. **记忆增强**：对话上下文 + Agent 长期记忆 + 向量语义搜索
6. **热更新配置**：数据库配置覆盖 .env，无需重启

### 项目目录结构

```
quest3-agent/
├── app/
│   ├── main.py                    # 应用入口，服务初始化和路由注册
│   ├── config.py                  # Pydantic Settings 配置管理
│   ├── api/                       # API 层（表现层）
│   │   ├── chat.py                # 聊天 API（含 WebSocket）
│   │   ├── agents.py              # Agent 管理 API
│   │   ├── collaborations.py      # 协作管理 API
│   │   ├── a2a.py                 # A2A 协议 API
│   │   ├── skills.py              # 技能管理 API
│   │   ├── mcp_servers.py         # MCP 服务器管理 API
│   │   ├── sessions.py            # 会话管理 API
│   │   ├── memory.py              # 记忆管理 API
│   │   ├── settings.py            # 系统设置 API
│   │   └── users.py               # 用户管理 API
│   ├── core/                      # 核心引擎层
│   │   ├── react_cot_executor.py  # ReAct + 思维链执行器
│   │   ├── execution.py           # 工具执行引擎（带重试）
│   │   ├── decision.py            # LLM 决策引擎
│   │   ├── strategy_router.py     # 策略路由器
│   │   └── tool_manager.py        # 统一工具管理器
│   ├── services/                  # 服务层
│   │   ├── llm_service.py         # 火山引擎 LLM 服务
│   │   ├── mcp_pool.py            # MCP 客户端连接池
│   │   ├── mcp_service.py         # MCP 工具管理服务
│   │   ├── agent_service.py       # Agent 配置管理
│   │   ├── agent_registry.py      # Agent 注册中心
│   │   ├── agent_memory_service.py# Agent 长期记忆服务
│   │   ├── collaboration_service.py # 协作配置管理
│   │   ├── collaboration_engine.py  # 协作执行引擎
│   │   ├── session_working_memory.py # 会话工作记忆
│   │   ├── vector_service.py      # ChromaDB 向量存储
│   │   ├── planning_chat_service.py # 规划聊天服务
│   │   ├── a2a_adapter.py         # A2A 协议适配器
│   │   ├── settings_service.py    # 设置管理服务
│   │   ├── user_service.py        # 用户管理服务
│   │   └── collaboration/         # 协作模式实现
│   │       ├── base.py            # 协作模式基类
│   │       ├── supervisor.py      # 监督者模式
│   │       ├── pipeline.py        # 流水线模式
│   │       ├── voting.py          # 投票模式
│   │       └── game.py            # 对抗博弈模式
│   ├── models/                    # 数据模型层
│   │   ├── agent.py               # Agent 模型
│   │   ├── chat.py                # 聊天模型
│   │   ├── session.py             # 会话模型
│   │   ├── collaboration.py       # 协作模型
│   │   ├── a2a.py                 # A2A 协议模型
│   │   ├── skill.py               # 技能模型
│   │   ├── memory.py              # 记忆模型
│   │   └── agent_memory.py        # Agent 记忆模型
│   ├── database/                  # 数据访问层
│   │   ├── connection.py          # 数据库连接管理
│   │   ├── repositories.py        # 数据仓库
│   │   ├── skill_repository.py    # 技能数据仓库
│   │   ├── mcp_schema.py          # MCP 表结构
│   │   └── settings_schema.py     # 设置表结构
│   ├── tools/                     # 本地工具
│   │   ├── base.py                # 工具基类
│   │   ├── filesystem.py          # 文件系统工具
│   │   └── web_search.py          # 网络搜索工具
│   └── skills/                    # 技能系统
│       ├── registry.py            # 技能注册中心
│       ├── loader.py              # 技能加载器
│       ├── executor.py            # 技能执行引擎
│       ├── trigger.py             # 触发器
│       ├── templates.py           # 技能模板
│       ├── dependencies.py        # 依赖管理
│       ├── file_manager.py        # 文件管理
│       ├── skill_writer.py        # 技能编写器
│       └── github_importer.py     # GitHub 导入器
├── skills/                        # 技能目录
│   ├── builtin/                   # 内置技能
│   ├── user/                      # 用户技能
│   └── cached/                    # 缓存（GitHub导入）技能
├── static/                        # 前端静态文件
├── doc/                           # 文档
├── pyproject.toml                 # 项目配置
└── main.py                        # 启动脚本
```

---

## 2. 技术栈详解

### 2.1 FastAPI：现代异步 Web 框架

**选择理由**：原生 async/await、自动 OpenAPI 文档、Pydantic 验证、依赖注入、WebSocket 支持。

```python
# 应用生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：初始化数据库、MCP 连接、Agent 注册、技能系统
    await db.initialize_schema()
    await settings.reload_from_db(db)
    await agent_registry.initialize()
    await initialize_skills()
    yield
    # 关闭：清理 MCP 连接、数据库连接
    await mcp_client_pool.close_all()
    await db.disconnect()
```

**在本项目中的使用**：
- 11 个 API Router（chat, agents, collaborations, a2a, skills, mcp_servers, sessions, memory, settings, users, mcp）
- WebSocket 端点用于流式聊天
- 依赖注入管理服务实例生命周期
- 静态文件服务（前端 SPA）

### 2.2 Volcengine SDK：火山引擎 LLM 客户端

**核心 API**：`volcenginesdkarkruntime.Ark`

```python
from volcenginesdkarkruntime import Ark

client = Ark(base_url="https://ark.cn-beijing.volces.com/api/v3", api_key=key)

# 深度思考模式
completion = client.chat.completions.create(
    model="doubao-seed-2.0-lite-260215",
    messages=[...],
    stream=True,
    thinking={"type": "enabled"},      # 启用深度思考
    reasoning_effort="medium",          # minimal/low/medium/high
    tools=[...],                        # 工具调用
)
```

**深度思考 API 特性**：
- `reasoning_content`：模型内部思考过程（流式输出）
- `content`：最终回答内容
- `tool_calls`：工具调用指令
- `reasoning_effort`：控制思考深度

### 2.3 ChromaDB：向量数据库

用于 Agent 长期记忆的语义搜索。每个 Agent 拥有独立的 Collection (`agent_{id}`)，支持：
- 自动 Embedding：文本自动转为向量
- 语义搜索：基于余弦相似度检索
- 元数据过滤：按记忆类型、重要性过滤
- 持久化存储：数据保存到本地文件系统

### 2.4 aiosqlite：异步 SQLite

全异步数据库操作，配合 WAL 模式支持读写并发：

```python
await db.execute("PRAGMA journal_mode = WAL")     # 写前日志
await db.execute("PRAGMA foreign_keys = ON")       # 外键约束
await db.execute("PRAGMA synchronous = NORMAL")    # 性能优化
```

### 2.5 Pydantic v2：数据验证与设置管理

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )
    VOLCENGINE_API_KEY: str = Field(default="")
    # ... 支持从数据库热更新
```

---

## 3. 系统架构总览

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    表现层 (API Layer)                        │
│  chat.py · agents.py · collaborations.py · a2a.py           │
│  skills.py · mcp_servers.py · sessions.py · memory.py       │
│  settings.py · users.py                                     │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    核心引擎层 (Core Layer)                   │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────────────┐  │
│  │ReActCot     │ │Decision      │ │Strategy             │  │
│  │Executor     │ │Engine        │ │Router               │  │
│  └──────┬──────┘ └──────┬───────┘ └──────────┬──────────┘  │
│         │               │                     │             │
│  ┌──────▼───────────────▼─────────────────────▼──────────┐  │
│  │              UnifiedToolManager                       │  │
│  └──────────────────────┬───────────────────────────────┘  │
│  ┌──────────────────────▼───────────────────────────────┐  │
│  │              ExecutionEngine (with retry)             │  │
│  └──────────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    服务层 (Service Layer)                    │
│  LLMService · MCPClientPool · AgentService                  │
│  AgentMemoryService · CollaborationService                  │
│  SessionWorkingMemory · VectorService                       │
│  PlanningChatService · A2AAdapter · SkillExecutor           │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│                    数据层 (Data Layer)                       │
│  DatabaseConnection · Repositories · ChromaDB               │
│  SQLite (agents, sessions, messages, memories, ...)          │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心请求流程

#### 直接对话模式 (direct)

```
用户消息 → WebSocket → chat.py
  → StrategyRouter.execute()
    → LLMService._chat_completion_stream_with_thinking()
      → 火山引擎 API (thinking + content 流式输出)
    → 流式事件 → WebSocket → 前端
```

#### ReAct 模式 (react)

```
用户消息 → WebSocket → chat.py
  → ReActCotExecutor.execute()
    → 循环：
      1. LLM 思考 (thinking) → 流式输出
      2. 工具调用决策 (tool_calls) → 解析
      3. 工具执行 → UnifiedToolManager.call_tool()
      4. 观察结果 → 注入消息历史
      5. 继续思考 或 结束
    → 流式事件 → WebSocket → 前端
```

#### 规划执行模式 (plan)

```
用户消息 → WebSocket → chat.py
  → PlanningChatService.chat()
    → DecisionEngine.analyze_task()
      → LLM 分析任务复杂度、选择策略
      → 返回 ExecutionPlan
    → ExecutionEngine.execute_plan()
      → 按策略执行：single / chain / parallel / mixed / thinking
      → 每步调用 UnifiedToolManager.call_tool()
    → 流式事件 → WebSocket → 前端
```

#### 多智能体协作模式

```
用户消息 → API → CollaborationEngine
  → 根据 CollaborationMode 选择协作模式
    → SupervisorMode: 主管拆分 → 子Agent并行执行 → 主管汇总
    → PipelineMode:  多Agent串行处理
    → VotingMode:    多Agent投票 → 聚合
    → GameMode:      多Agent对抗 → 裁判评判
  → AgentRegistry.call_agent() → A2AAdapter → Agent执行
  → 结果汇总 → 返回
```

---

## 4. 核心模块详解

### 4.1 应用入口 (app/main.py)

`main.py` 是整个应用的启动点，负责：

1. **服务初始化**：数据库、LLM、记忆、向量、MCP
2. **工具注册**：将本地工具（FileSystem、WebSearch）注册到 UnifiedToolManager
3. **引擎连接**：将 LLM 服务注入 DecisionEngine 和 StrategyRouter
4. **MCP 服务器连接**：从数据库加载并连接已启用的 MCP 服务器
5. **Agent 注册**：初始化 AgentRegistry，注册所有已启用的 Agent
6. **技能系统初始化**：扫描并加载技能

```python
# 关键初始化流程
db = DatabaseConnection(settings.DATABASE_URL)
llm_service = LLMService()
memory_service = SessionWorkingMemory()
vector_service = VectorService()
agent_memory_service.set_vector_service(vector_service)

# 统一工具管理器
tool_manager = get_tool_manager()
tool_manager.register_local_tool(name, description, input_schema, handler, source)

# MCP 客户端池
mcp_client_pool = MCPClientPool()

# Agent 注册中心
agent_registry = AgentRegistry()
```

### 4.2 配置模块 (app/config.py)

使用 Pydantic Settings 管理配置，支持从 `.env` 文件和数据库读取：

```python
class Settings(BaseSettings):
    # 火山引擎 LLM 配置
    VOLCENGINE_API_KEY: str = Field(default="")
    VOLCENGINE_BASE_URL: str = Field(default="https://ark.cn-beijing.volces.com/api/v3")
    VOLCENGINE_MODEL: str = Field(default="doubao-seed-2.0-lite-260215")
    VOLCENGINE_DEFAULT_REASONING_EFFORT: str = Field(default="medium")

    # 记忆配置
    MEMORY_MAX_RECENT_MESSAGES: int = Field(default=20)
    MEMORY_SUMMARY_THRESHOLD: int = Field(default=30)
    MEMORY_AUTO_EXTRACT: bool = Field(default=True)
    MEMORY_IMPORTANCE_THRESHOLD: float = Field(default=0.3)

    # 技能目录配置
    SKILLS_BASE_DIR: str = Field(default="./skills")
    SKILLS_BUILTIN_DIR: str = Field(default="./skills/builtin")
    SKILLS_USER_DIR: str = Field(default="./skills/user")
    SKILLS_CACHED_DIR: str = Field(default="./skills/cached")
```

**配置优先级**：系统环境变量 > 数据库值 > .env 文件 > 默认值

**热更新机制**：`reload_from_db()` 从数据库读取配置并覆盖当前值，无需重启应用。

---

## 5. Agent 智能体系统

### 5.1 Agent 数据模型

每个 Agent 拥有独立的配置，决定其行为方式：

```python
class AgentResponse(BaseModel):
    id: str
    name: str
    description: str
    type: AgentType                          # chat / coder / researcher / custom
    execution_mode: str                      # plan / react / direct
    system_prompt: str                       # 系统提示词
    model: Optional[str]                     # 使用的模型
    temperature: Optional[float]             # 温度
    max_tokens: Optional[int]                # 最大 token 数
    mcp_servers: List[Dict[str, Any]]        # 绑定的 MCP 服务器
    tools: List[str]                         # 启用的工具白名单
    skills: List[str]                        # 绑定的技能
    thinking_effort: str                     # 思考深度: low / medium / high
    max_react_steps: int                     # ReAct 最大步数
    enable_long_term_memory: bool            # 是否启用长期记忆
```

### 5.2 执行模式

Agent 支持 4 种执行模式，决定任务如何被处理：

| 模式 | 执行器 | 适用场景 |
|------|--------|---------|
| `direct` | StrategyRouter | 简单对话，无需工具 |
| `plan` | DecisionEngine + ExecutionEngine | 复杂任务，需要规划再执行 |
| `react` | ReActCotExecutor | 需要深度思考+工具调用的循环任务 |

### 5.3 Agent 服务 (app/services/agent_service.py)

提供 Agent 的 CRUD 操作：

- **create**：创建 Agent，绑定 MCP 服务器、工具、技能
- **get/list**：查询 Agent 配置
- **update**：更新 Agent 配置，同步到注册中心
- **delete**：删除 Agent 及其记忆（SQLite + ChromaDB）
- **increment_usage**：使用计数统计
- **_sync_agent_skills_to_registry**：同步技能绑定到内存注册中心

---

## 6. 执行引擎与策略路由

### 6.1 ReAct + 思维链执行器 (ReActCotExecutor)

这是本项目最核心的执行器，实现了 ReAct（Reasoning + Acting）范式与思维链的结合：

```
循环执行：
  Think  → LLM 深度思考（reasoning_content 流式输出）
  Act    → LLM 决定调用工具（tool_calls）
  Observe → 执行工具，获取结果
  ...重复，直到 LLM 认为任务完成或达到最大步数
```

**核心流程**：

```python
class ReActCotExecutor:
    async def execute(self, task, conversation_history, deep_thinking=True):
        # 1. 初始化：获取可用工具
        await self._initialize()

        # 2. 构建消息列表：system_prompt + 对话历史 + 时间提醒 + 当前任务
        messages = self._build_messages(...)

        # 3. 主循环
        for step in range(1, self.max_steps + 1):
            # 3a. 调用 LLM（流式，带深度思考 + 工具调用）
            async for event in llm_service._chat_completion_stream_with_tools(
                messages, tools=tools, enable_thinking=True, ...
            ):
                if event["type"] == "thinking":
                    yield {"type": "cot_thinking", "content": ...}
                elif event["type"] == "content":
                    # 缓冲 content，待确认是否最终答案
                elif event["type"] == "tool_calls":
                    # 累加 tool_calls

            # 3b. 如果有工具调用 → 执行工具
            if tool_calls_to_execute:
                for tool_call in tool_calls_to_execute:
                    result = await self._execute_tool(tool_name, tool_args)
                    messages.append({"role": "tool", "content": result})

            # 3c. 如果没有工具调用 → 任务完成
            else:
                yield {"type": "cot_complete", "message": final_response}
                break
```

**事件类型**（前端消费）：

| 事件 | 说明 |
|------|------|
| `cot_step_start` | 新步骤开始 |
| `cot_phase` | 当前阶段：thinking / tool-call / observation / summarizing / complete |
| `cot_thinking` | 思考内容（流式） |
| `cot_action` | 工具调用信息 |
| `cot_observation` | 工具执行结果 |
| `cot_complete` | 任务完成，最终回复 |
| `message` | 最终回复内容（流式） |
| `error` | 错误信息 |
| `end` | 执行结束 |

**关键设计决策**：
- 使用火山引擎官方 `tool_calls` 机制（而非正则解析）
- 单个连贯的思维链容器（而非每步独立）
- `reasoning_content` 是思考过程，`content` 是最终回答
- 当 `content` 为空但 `thinking_content` 很长时，提取思考内容作为回答

### 6.2 ReAct 执行器 (ReActExecutor)

`react_executor.py` 是一个**兼容性包装器**，委托给 `ReActCotExecutor`，将新事件格式翻译为旧事件格式：

```python
class ReActExecutor:
    async def execute(self, task, ...):
        executor = ReActCotExecutor(agent_config=self.agent_config)
        async for event in executor.execute(task, ...):
            # cot_step_start → thinking_start
            # cot_thinking   → thinking
            # cot_action     → action_start
            # cot_observation → observation
            # cot_complete   → complete
```

### 6.3 策略路由器 (StrategyRouter)

用于 `direct` 执行模式，直接调用 LLM 进行对话（带深度思考支持）：

```python
class ExecutionStrategyRouter:
    async def execute(self, task, agent_config, conversation_history, deep_thinking):
        async for content, thinking in llm_service._chat_completion_stream_with_thinking(
            messages, enable_thinking=deep_thinking, ...
        ):
            if thinking:
                yield {"type": "thinking", "content": thinking}
            elif content:
                yield {"type": "message", "content": content}
```

### 6.4 决策引擎 (DecisionEngine)

用于 `plan` 执行模式，由 LLM 分析任务并制定执行计划：

```python
class ToolDecisionEngine:
    async def analyze_task(self, user_message, ...):
        # 1. 获取可用工具列表
        tools = await tool_manager.get_tools_for_llm(...)

        # 2. 构建决策提示词，让 LLM 返回 JSON 格式的执行计划
        prompt = self._create_decision_prompt(user_message, tools, ...)

        # 3. 调用 LLM（可选深度思考）
        response = await llm_service.chat(prompt)

        # 4. 解析 LLM 返回的 JSON 执行计划
        plan = self._parse_llm_response(response, user_message)
        return plan  # ExecutionPlan
```

**执行计划结构**：

```python
@dataclass
class ExecutionPlan:
    plan_id: str
    complexity: ComplexityLevel    # SIMPLE / MEDIUM / COMPLEX
    strategy: ExecutionStrategy    # single / chain / parallel / mixed / thinking
    description: str
    steps: List[ExecutionStep]     # 具体执行步骤

@dataclass
class ExecutionStep:
    step_id: str
    tool_name: str
    arguments: Dict[str, Any]
    depends_on: List[str]          # 依赖的前序步骤
    parallel: bool                 # 是否可并行
    max_retries: int = 3
```

### 6.5 工具执行引擎 (ExecutionEngine)

按执行计划运行，支持 5 种策略：

| 策略 | 说明 |
|------|------|
| `single` | 单步执行 |
| `chain` | 链式执行（步骤按顺序，结果传递） |
| `parallel` | 并行执行（独立步骤同时运行） |
| `mixed` | 混合执行（并行+链式组合） |
| `thinking` | 纯深度思考（不调用工具） |

**智能重试机制**：

```python
async def _execute_step(self, step):
    while step.retry_count <= step.max_retries:
        try:
            result = await tool_manager.call_tool(step.tool_name, step.arguments)
            return result
        except Exception as e:
            error_type = self._classify_error(e)  # network/timeout/parameter/tool_not_found/permission
            retry_delay = self._get_retry_delay(error_type, step.retry_count)
            await asyncio.sleep(retry_delay)
```

---

## 7. 统一工具管理系统

### 7.1 UnifiedToolManager

统一管理三类工具，提供一致的访问接口：

```python
class UnifiedToolManager:
    def __init__(self):
        self._local_tools: Dict[str, ToolDefinition] = {}

    # 注册本地工具（包括技能工具）
    def register_local_tool(self, name, description, input_schema, handler, source)

    # 注册技能工具（load_skill, execute_skill）
    def register_skill_tools(self)

    # 获取所有可用工具
    async def get_available_tools(
        self,
        enabled_mcp_servers=None,  # 启用的 MCP 服务器列表
        allowed_tools=None          # 工具白名单
    ) -> Dict[str, ToolDefinition]

    # 获取 LLM 格式的工具列表
    async def get_tools_for_llm(...) -> List[Dict]

    # 调用工具
    async def call_tool(self, tool_name, arguments) -> Any
```

### 7.2 工具来源

| 来源 | 说明 | 示例 |
|------|------|------|
| `local` | 代码内定义的本地工具 | `read_file`, `write_file`, `web_search` |
| `mcp` | MCP 远程服务器提供的工具 | `execute_code`, `query_database` |
| `skill` | 技能系统提供的工具 | `load_skill`, `execute_skill` |

### 7.3 工具白名单过滤逻辑

`allowed_tools` 参数控制工具可见范围：

- `allowed_tools=None`：不过滤，加载已绑定 server 的全部工具
- `allowed_tools=[]`：加载已绑定 server 的全部工具 + skill 工具
- `allowed_tools=["web_search"]`：混合逻辑：白名单中的工具放行；对于没有任何工具被选中的 server，其全部工具也放行

```python
# 核心过滤逻辑
if allowed_tools is not None:
    allowed_set = set(allowed_tools)
    allowed_set.add("load_skill")       # 始终包含
    allowed_set.add("execute_skill")    # 始终包含

    # 找出没有工具被选中的 server
    servers_with_no_tools_selected = {
        sid for sid in mcp_server_set
        if not any(v.server_id == sid and k in allowed_set for k, v in tools.items())
    }

    # 白名单工具 + 无工具被选中的 server 全部工具
    tools = {k: v for k, v in tools.items()
             if k in allowed_set or (v.server_id in servers_with_no_tools_selected and v.source == "mcp")}
```

### 7.4 工具调用路由

```python
async def call_tool(self, tool_name, arguments):
    # 1. 先检查本地工具（包括技能工具）
    if tool_name in self._local_tools:
        return await self._local_tools[tool_name].handler(**arguments)

    # 2. 否则通过 MCP 客户端池调用远程工具
    return await mcp_client_pool.call_tool(tool_name, arguments)
```

---

## 8. MCP 服务器与客户端池

### 8.1 MCP 客户端池 (MCPClientPool)

管理多个 MCP 服务器连接，支持标准 MCP 和 Streamable HTTP 两种模式：

```python
class MCPClientPool:
    connections: Dict[str, MCPServerConnection]  # 服务器连接池
    local_tools: Dict[str, Any]                   # 本地工具

    # 添加服务器
    async def add_server(self, config: MCPServerConfig) -> bool

    # 获取所有工具（本地 + 远程）
    async def get_all_tools(self) -> Dict[str, Any]

    # 调用工具（自动路由到本地或远程）
    async def call_tool(self, tool_name, arguments, timeout=60) -> Any
```

### 8.2 服务器配置

```python
@dataclass
class MCPServerConfig:
    id: str                # 服务器唯一 ID
    name: str              # 显示名称
    url: str               # 服务器地址
    server_type: str       # "standard" 或 "streamable"
    headers: Dict[str,str] # 自定义请求头（如认证）
    priority: int          # 优先级
    short_id: str          # 工具名前缀（ID 前8位）
```

### 8.3 工具名前缀机制

为避免不同服务器的工具名冲突，远程工具使用 `short_id_` 前缀：

```
本地工具：  web_search, read_file, write_file
远程工具：  1693271f_execute_code, 1693271f_query_db
```

### 8.4 两种服务器模式

| 模式 | 连接方式 | 工具列表 | 工具调用 |
|------|---------|---------|---------|
| `standard` | `POST {url}/tools/list` | `POST {url}/tools/list` | `POST {url}/tools/call` |
| `streamable` | `POST {url}` (streaming) | `POST {url}` (tools/list) | `POST {url}` (tools/call) |

### 8.5 健康检查

每个服务器连接启动后，自动创建健康检查任务：

```python
async def health_check():
    while True:
        await asyncio.sleep(connection.health_check_interval)
        try:
            await connection.client.post(f"{url}/ping", ...)
        except Exception:
            logger.warning(f"Health check failed for {name}")
```

---

## 9. 技能系统 (Skill System)

### 9.1 概述

技能系统让 Agent 能够扩展能力，每个技能由一个 `skill.md` 文件定义，可选配有可执行脚本。

**技能目录结构**：

```
skills/
├── builtin/                    # 内置技能
│   ├── code_reviewer/
│   │   └── skill.md
│   ├── web_research/
│   │   └── skill.md
│   └── doc_generator/
│       └── skill.md
├── user/                       # 用户自定义技能
│   ├── example_script/
│   │   ├── skill.md
│   │   └── main.py             # 可执行入口
│   ├── memory_manager/
│   │   ├── skill.md
│   │   └── README.md
│   └── python计算机/
│       └── skill.md
└── cached/                     # GitHub 导入的缓存技能
    └── alchaincyf_zhangxuefeng-skill/
        ├── SKILL.md
        ├── README.md
        ├── examples/
        └── references/
```

### 9.2 技能模型

```python
class Skill(BaseModel):
    id: str                     # 唯一标识
    name: str                   # 技能名称
    description: str            # 描述
    tags: List[str]             # 标签
    content: str                # skill.md 全文内容
    dir_path: Optional[str]     # 技能目录路径
    entrypoint: Optional[str]   # 入口脚本路径（如 main.py）
    source: SkillSource         # builtin / user / github
```

### 9.3 技能注册中心 (SkillRegistry)

管理技能的加载、查询和 Agent 关联：

```python
class SkillRegistry:
    def initialize(self)                    # 扫描并加载所有技能
    def get_skill(self, skill_name)         # 按名称获取技能
    def get_agent_skills(self, agent_id)    # 获取 Agent 绑定的技能
    def get_system_prompt_addition(self, agent_id)  # 注入技能提示到 system prompt
    def link_agent_skill(self, link)        # 绑定技能到 Agent
    def search_skills(self, query)          # 搜索技能
    async def import_from_github(self, repo_ref)  # 从 GitHub 导入
```

### 9.4 技能执行流程

1. **Agent 接收用户消息**，system_prompt 中包含可用技能列表
2. **Agent 判断需要使用技能**，调用 `load_skill` 工具加载技能说明书
3. **如果 `has_entrypoint=true`**，Agent 调用 `execute_skill` 工具执行脚本
4. **如果 `has_entrypoint=false`**，Agent 根据技能说明书给出指导建议

```python
# 技能工具在 UnifiedToolManager 中注册
load_skill_handler(skill_name) → {
    "skill_name": "...",
    "content": "技能说明书全文",
    "has_entrypoint": True/False,
    "message": "Successfully loaded skill: ..."
}

execute_skill_handler(skill_name, input_data, session_id) → {
    "status": "success/error",
    "output": "...",
    "execution_time_ms": 123,
    "logs": [...]
}
```

### 9.5 技能执行引擎 (SkillExecutor)

执行技能的可执行脚本（`main.py`、`main.sh`、`main.ps1`）：

```python
class SkillExecutionContext(BaseModel):
    session_id: str            # 会话 ID（支持跨调用状态保持）
    skill_id: str
    skill_name: str
    input_data: Dict[str, Any] # 用户输入
    config: Dict[str, Any]     # 技能配置
    state: Dict[str, Any]      # 执行状态（可写）
```

### 9.6 GitHub 导入

支持从 GitHub 仓库导入技能：

```python
await skill_registry.import_from_github(
    repo_ref="username/skill-repo",
    auto_enable=True,
    force_refresh=False
)
```

---

## 10. 多智能体协作

### 10.1 协作模式

支持 4 种协作模式，每种模式定义了 Agent 之间的交互方式：

| 模式 | 说明 | Agent 角色 |
|------|------|-----------|
| `supervisor` | 监督者模式 | 1 个 Supervisor + N 个 Child |
| `pipeline` | 流水线模式 | N 个 Worker 串行 |
| `voting` | 投票模式 | N 个 Voter + 1 个 Aggregator |
| `adversarial_game` | 对抗博弈 | N 个 Participant + 1 个 Referee |

### 10.2 监督者模式 (Supervisor)

```
输入任务 → Supervisor 拆分子任务
  → Child1 执行子任务1 ─┐
  → Child2 执行子任务2 ─┤（可并行）
  → Child3 执行子任务3 ─┘
  → Supervisor 汇总结果 → 最终输出
```

```python
class SupervisorCollaboration(BaseCollaborationMode):
    async def execute(self, collab, input_text):
        # Step 1: Supervisor 拆分任务
        split_result = await agent_registry.call_agent(supervisor_id, split_task)
        sub_tasks = self._parse_subtasks(split_result.output)

        # Step 2: Child Agents 执行（并行或串行）
        child_results = await self._execute_children(sub_tasks, ...)

        # Step 3: Supervisor 汇总
        summary_result = await agent_registry.call_agent(supervisor_id, summary_task)
        task.set_completed(summary_result.output)
```

### 10.3 流水线模式 (Pipeline)

```
输入 → Worker1 处理 → Worker2 处理 → Worker3 处理 → 最终输出
```

每个 Worker 的输出作为下一个 Worker 的输入。

### 10.4 投票模式 (Voting)

```
输入 → Voter1 投票 ─┐
     → Voter2 投票 ─┤→ Aggregator 聚合 → 最终输出
     → Voter3 投票 ─┘
```

### 10.5 对抗博弈模式 (Adversarial Game)

```
裁判宣布规则 → Participant1 出招 → Participant2 出招 → ... → 裁判评判
     ↑                                                    ↓
     └──────────── 下一轮（最多 max_rounds 轮）────────────┘
```

配置选项：

```python
class AdversarialGameConfig(BaseModel):
    turn_strategy: str       # "simultaneous" 或 "sequential"
    referee_timing: str      # "per_round" 或 "final"
    max_rounds: int          # 最大轮数
    game_rules: str          # 游戏规则
    participant_order: List[str]  # 出手顺序
    shared_state: Dict[str, Any]  # 共享状态
    referee_enabled: bool    # 是否启用裁判
```

### 10.6 协作引擎 (CollaborationEngine)

根据协作模式分发到对应的执行器：

```python
class CollaborationEngine:
    def _get_mode(self, collab: CollaborationResponse) -> BaseCollaborationMode:
        if collab.mode == CollaborationMode.SUPERVISOR:
            return SupervisorCollaboration()
        elif collab.mode == CollaborationMode.PIPELINE:
            return PipelineCollaboration()
        elif collab.mode == CollaborationMode.VOTING:
            return VotingCollaboration()
        elif collab.mode == CollaborationMode.ADVERSARIAL_GAME:
            return AdversarialGameCollaboration()
```

---

## 11. A2A 协议与 Agent 注册中心

### 11.1 A2A (Agent-to-Agent) 协议

A2A 是一种标准化协议，定义 Agent 之间的通信方式。本项目实现了 A2A 适配器，将现有 Agent 包装为 A2A 兼容形式。

### 11.2 Agent 注册中心 (AgentRegistry)

进程内的 Agent 实例注册表，管理所有活跃的 Agent：

```python
class AgentRegistry:
    _agents: Dict[str, A2AAdapter]     # Agent 适配器
    _agent_cards: Dict[str, AgentCard] # Agent 卡片（A2A 元数据）

    async def initialize(self)                    # 从数据库加载所有已启用的 Agent
    async def register_existing_agent(self, agent) # 注册已有 Agent
    async def call_agent(self, agent_id, task)     # 调用 Agent 执行任务
    def unregister(self, agent_id)                 # 取消注册
```

### 11.3 A2A 适配器 (A2AAdapter)

将 Agent 包装为 A2A 兼容接口：

```python
class A2AAdapter:
    def __init__(self, agent: AgentResponse):
        self.agent = agent

    async def get_agent_card(self) -> AgentCard:
        """返回 Agent 的 A2A 元数据卡片"""

    async def call(self, task: A2ATask) -> A2ATask:
        """执行 A2A 任务：构建消息 → 调用 LLM → 返回结果"""
```

---

## 12. 记忆系统

### 12.1 记忆层次

```
┌───────────────────────────────────────────────────────┐
│                  记忆系统架构                          │
├───────────────────────────────────────────────────────┤
│  工作记忆 (SessionWorkingMemory)                       │
│  - 当前对话上下文（最近 20 条消息）                    │
│  - 摘要压缩（超过 30 条时自动摘要）                    │
│  - 存储在内存 + SQLite                                │
├───────────────────────────────────────────────────────┤
│  Agent 长期记忆 (AgentMemoryService)                   │
│  - 偏好 (preference)：几乎不衰减                       │
│  - 事实 (fact)：中等衰减                               │
│  - 事件 (event)：快速衰减                              │
│  - 存储在 SQLite + ChromaDB                           │
│  - 语义搜索 + 重要性衰减                               │
└───────────────────────────────────────────────────────┘
```

### 12.2 SessionWorkingMemory

统一的会话工作记忆，合并了原有的 MemoryService 和 ConversationContext：

```python
class SessionWorkingMemory:
    def add_message(self, session_id, role, content)   # 添加消息
    def get_conversation_history(self, session_id)      # 获取对话历史
    async def maybe_summarize(self, session_id)         # 超过阈值时自动摘要
    def load_from_db(self, session_id, messages)        # 从数据库加载历史
```

**摘要触发**：当消息数超过 `MEMORY_SUMMARY_THRESHOLD`（默认 30）时，自动调用 LLM 将旧消息压缩为摘要。

### 12.3 Agent 长期记忆 (AgentMemoryService)

Agent 级别的跨会话记忆系统：

**记忆提取**（对话结束时自动触发）：

```python
MEMORY_EXTRACTION_PROMPT = """分析以下完整对话记录，提取需要长期记住的信息。
- 用户明确表达的偏好/习惯 → type: "preference", importance: 0.8-1.0
- 重要事实/事件 → type: "fact", importance: 0.5-0.8
- 值得记住的上下文 → type: "event", importance: 0.3-0.5
- 闲聊/客套/临时信息 → 不提取
"""
```

**记忆召回**（对话开始时自动注入）：

```python
async def recall(self, agent_id, query, n=5, min_importance=0.3):
    # 1. 优先从 ChromaDB 语义搜索
    results = vector_service.search(agent_id, query, n_results=n*2)
    # 2. 计算有效重要性（含衰减）
    # 3. 按有效重要性排序返回
```

**重要性衰减**：

```python
DECAY_LAMBDA_BY_TYPE = {
    "preference": 0.005,  # 半衰期 ~140 天
    "fact": 0.023,        # 半衰期 ~30 天
    "event": 0.099,       # 半衰期 ~7 天
    "summary": 0.023,
}

def _effective_importance(self, memory):
    # 基础衰减：importance * exp(-lambda * days)
    # 访问频率减缓衰减：每次访问等效延长半衰期
    access_slowdown = 1.0 + 0.1 * min(access_count, 20)
    effective_decay = exp(-lambda * days / access_slowdown)
    return importance * effective_decay
```

**记忆整合**：

```python
async def consolidate(self, agent_id):
    # 1. 删除有效重要性过低的记忆 (< 0.1)
    # 2. 合并内容相似的记忆（前50字符匹配）
```

**记忆注入流程**（在 chat.py 中）：

```python
async def _inject_memory_into_agent_config(agent_config_dict, agent_id, user_message):
    # 1. 获取记忆画像（高重要性的偏好和事实）
    profile = await agent_memory_service.get_agent_profile(agent_id)
    # 2. 语义召回相关记忆
    recalled = await agent_memory_service.recall(agent_id, user_message, n=5)
    # 3. 注入到 system_prompt
    agent_config_dict["system_prompt"] += memory_block
```

### 12.4 向量服务 (VectorService)

基于 ChromaDB 的向量存储，为 Agent 记忆提供语义搜索：

```python
class VectorService:
    def add(self, agent_id, content, metadata)    # 添加向量
    def search(self, agent_id, query, n_results)  # 语义搜索
    def delete(self, agent_id, memory_id)         # 删除向量
    def get_or_create_collection(self, agent_id)  # 获取/创建集合
```

---

## 13. LLM 服务层

### 13.1 LLMService

封装火山引擎 SDK，提供多种调用方式：

| 方法 | 说明 |
|------|------|
| `chat()` | 非流式对话，支持自动续写 |
| `chat_stream()` | 流式对话，支持深度思考标记 |
| `_chat_completion()` | 底层非流式调用，带自动续写 |
| `_chat_completion_stream()` | 底层流式调用（无思考） |
| `_chat_completion_stream_with_thinking()` | 流式调用（带思考） |
| `_chat_completion_stream_with_tools()` | 流式调用（带思考+工具） |

### 13.2 深度思考流式处理

火山引擎深度思考 API 返回两种内容：
- `reasoning_content`：模型内部思考过程
- `content`：最终回答

```python
async def _chat_completion_stream_with_thinking(self, messages, ...):
    def run_sync_stream():
        api_params["thinking"] = {"type": "enabled"}
        api_params["reasoning_effort"] = reasoning_effort

        for chunk in completion:
            if chunk.choices[0].delta.reasoning_content:
                chunk_queue.put(("thinking", content))
            if chunk.choices[0].delta.content:
                chunk_queue.put(("content", content))
```

**异步桥接**：SDK 是同步的，通过后台线程 + Queue 桥接到 asyncio：

```python
thread = threading.Thread(target=run_sync_stream, daemon=True)
thread.start()

while True:
    chunk = await loop.run_in_executor(None, chunk_queue.get, True, 0.1)
    yield chunk
```

### 13.3 工具调用流式处理

```python
async def _chat_completion_stream_with_tools(self, messages, tools, ...):
    for chunk in completion:
        # 思考内容
        if chunk.choices[0].delta.reasoning_content:
            yield {"type": "thinking", "content": ...}
        # 回答内容
        if chunk.choices[0].delta.content:
            yield {"type": "content", "content": ...}
        # 工具调用
        if chunk.choices[0].delta.tool_calls:
            yield {"type": "tool_calls", "tool_calls": [...]}
```

### 13.4 自动续写

当 LLM 响应被截断时（`finish_reason=length`），自动发送续写请求：

```python
for attempt in range(max_continuations + 1):
    result_text, finish_reason = await loop.run_in_executor(...)
    full_response += result_text
    if finish_reason != "length":
        break
    # 追加截断的回复和续写请求
    current_messages.append({"role": "assistant", "content": result_text})
    current_messages.append({"role": "user", "content": "请继续输出..."})
```

### 13.5 重新配置

当 LLM 设置通过管理页面更新时，调用 `reconfigure()` 重建客户端：

```python
def reconfigure(self):
    self.api_key = settings.VOLCENGINE_API_KEY
    self.model = settings.VOLCENGINE_MODEL
    self.volc_client = Ark(base_url=..., api_key=self.api_key)
```

---

## 14. API 层设计

### 14.1 WebSocket 聊天 API

`/api/chat/stream` 是核心聊天端点，处理流程：

```
1. 接受连接 → 接收 session_id 和 agent_id
2. 加载历史消息 → 发送 history 事件
3. 消息循环：
   a. 接收用户消息
   b. 保存消息 → 加载到工作记忆
   c. 获取对话历史
   d. 构建 Agent 配置（system_prompt + 技能提示 + 记忆上下文）
   e. 根据执行模式选择执行器
   f. 流式发送事件
   g. 保存助手回复
4. 断开时提取长期记忆
```

### 14.2 REST API 列表

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/chat/chat` | POST | 发送聊天消息（非流式） |
| `/api/chat/stream` | WS | WebSocket 流式聊天 |
| `/api/sessions/` | GET/POST | 会话管理 |
| `/api/agents/` | GET/POST | Agent 管理 |
| `/api/collaborations/` | GET/POST | 协作管理 |
| `/api/a2a/` | POST | A2A 协议端点 |
| `/api/skills/` | GET | 技能管理 |
| `/api/mcp-servers/` | GET/POST | MCP 服务器管理 |
| `/api/memory/` | GET | 记忆管理 |
| `/api/settings/` | GET/PUT | 系统设置 |
| `/api/users/` | GET/POST | 用户管理 |
| `/health` | GET | 健康检查 |
| `/tools` | GET | 工具列表 |

---

## 15. 数据层设计

### 15.1 SQLite 数据表

| 表名 | 说明 |
|------|------|
| `sessions` | 会话记录 |
| `messages` | 消息记录 |
| `memory` | 会话级记忆 |
| `agents` | Agent 配置 |
| `agent_mcp_servers` | Agent-MCP 服务器绑定 |
| `agent_tools` | Agent-工具绑定 |
| `agent_skills` | Agent-技能绑定 |
| `agent_memories` | Agent 长期记忆 |
| `collaborations` | 协作配置 |
| `collaboration_agents` | 协作-Agent 绑定 |
| `collaboration_tasks` | 协作任务记录 |
| `mcp_servers` | MCP 服务器配置 |
| `app_settings` | 应用设置（键值对） |
| `users` | 用户管理 |

### 15.2 Repository 模式

数据访问通过 Repository 类封装：

```python
class SessionRepository:
    async def create(self, data) -> SessionCreateResponse
    async def get(self, session_id) -> Optional[SessionResponse]
    async def get_history(self, session_id, limit) -> List[Message]
    async def count_messages(self, session_id) -> int

class MessageRepository:
    async def create(self, data) -> Message
    async def get_by_session(self, session_id) -> List[Message]

class AgentMemoryRepository:
    async def create(self, agent_id, content, memory_type, importance, ...) -> str
    async def get_by_agent(self, agent_id, memory_type, limit) -> List[dict]
    async def search_similar_content(self, agent_id, content, limit) -> List[dict]
    async def update(self, memory_id, content, importance) -> None
    async def delete(self, memory_id) -> None
    async def count(self, agent_id) -> int
```

### 15.3 ChromaDB 向量存储

- 每个 Agent 一个 Collection（命名格式：`agent_{id}`）
- 支持语义搜索和元数据过滤
- 持久化存储在本地文件系统

---

## 16. 配置与热更新

### 16.1 双层配置

```
.env 文件 → Pydantic Settings → 应用运行
                ↑
数据库 app_settings 表 → reload_from_db() 覆盖
```

### 16.2 热更新流程

```python
# 设置 API 更新配置
@router.put("/settings")
async def update_settings(updates: dict):
    # 1. 写入数据库
    await settings_service.update_setting(key, value)
    # 2. 热更新内存中的 Settings 实例
    await settings.reload_from_db(db)
    # 3. 如果是 LLM 配置变更，重建 LLM 客户端
    if llm_related:
        llm_service.reconfigure()
```

### 16.3 默认管理员

启动时自动创建默认管理员用户：

```python
await user_service.ensure_default_admin()
```

---

## 17. 关键技术点深入

### 17.1 流式事件系统

整个聊天流程基于事件驱动，前端通过 WebSocket 接收事件流：

```
事件类型                     产生者                    说明
─────────────────────────────────────────────────────────────
connected                   chat.py                  连接建立
history                     chat.py                  历史消息
thinking_start              StrategyRouter/ReAct     思考开始
thinking                    StrategyRouter/ReAct     思考内容（流式）
thinking_end                StrategyRouter/ReAct     思考结束
message                     所有执行器               最终回复（流式）
phase                       ReActExecutor           当前阶段
action_start                ReActExecutor           工具调用开始
observation                 ReActExecutor           工具执行结果
cot_step_start              ReActCotExecutor        新步骤开始
cot_phase                   ReActCotExecutor        当前阶段
cot_thinking                ReActCotExecutor        思考内容
cot_action                  ReActCotExecutor        工具调用
cot_observation             ReActCotExecutor        观察结果
cot_complete                ReActCotExecutor        任务完成
execution_start             ExecutionEngine         执行计划开始
step_start                  ExecutionEngine         步骤开始
step_complete               ExecutionEngine         步骤完成
step_error                  ExecutionEngine         步骤错误
error                       所有执行器               错误
end                         所有执行器               结束
```

### 17.2 时间注入

为防止模型使用过时信息，在对话历史中注入时间提醒：

```python
current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
messages.append({
    "role": "system",
    "content": f"【提醒】当前日期时间：{current_time}，请基于此时间回答问题。"
})
```

注入位置：在对话历史之后、当前消息之前（而非 system prompt 头部），避免被长历史"淹没"。

### 17.3 异步桥接模式

火山引擎 SDK 是同步的，本项目通过 `threading + Queue + run_in_executor` 桥接到 asyncio：

```python
def run_sync_stream():
    for chunk in sync_client.chat.completions.create(stream=True):
        chunk_queue.put(chunk)

thread = threading.Thread(target=run_sync_stream, daemon=True)
thread.start()

async for chunk in async_wrapper(chunk_queue):
    yield chunk
```

### 17.4 全局单例模式

本项目大量使用全局单例来管理服务实例：

```python
# 模块级全局实例
llm_service = LLMService()
mcp_client_pool = MCPClientPool()
agent_memory_service = AgentMemoryService()
agent_registry = AgentRegistry()
decision_engine = ToolDecisionEngine()
execution_engine = ToolExecutionEngine()
strategy_router = ExecutionStrategyRouter()

# 工厂函数获取单例
def get_tool_manager() -> UnifiedToolManager: ...
def get_skill_registry() -> SkillRegistry: ...
```

### 17.5 错误分类与重试策略

```python
class ErrorType(str, Enum):
    NETWORK = "network"          # 指数退避重试
    TIMEOUT = "timeout"          # 立即重试
    PARAMETER = "parameter"      # 无延迟，需快速响应
    TOOL_NOT_FOUND = "tool_not_found"  # 无延迟
    PERMISSION = "permission"    # 不重试
    UNKNOWN = "unknown"          # 固定延迟
```

---

## 18. 设计模式应用

### 18.1 分层架构

API 层 → 核心引擎层 → 服务层 → 数据层，各层职责明确，依赖方向单一。

### 18.2 策略模式

- **执行策略**：`ExecutionStrategy`（single/chain/parallel/mixed/thinking）
- **协作模式**：`CollaborationMode`（supervisor/pipeline/voting/game）
- **执行模式**：`execution_mode`（direct/plan/react）

每种模式有独立的实现类，通过引擎分发。

### 18.3 适配器模式

`A2AAdapter` 将现有 Agent 包装为 A2A 兼容接口，无需修改 Agent 代码。

### 18.4 工厂模式

```python
def get_tool_manager() -> UnifiedToolManager:  # 延迟创建全局单例
def get_skill_registry() -> SkillRegistry:
```

### 18.5 观察者模式

`ExecutionEngine` 的事件回调系统：

```python
engine.register_callback(callback)   # 注册事件监听器
await engine._emit(event)            # 发射事件
```

### 18.6 Repository 模式

数据访问逻辑集中在 Repository 类中，业务层不直接操作 SQL。

### 18.7 依赖注入

FastAPI 的 `Depends()` 机制注入服务实例：

```python
async def get_dependencies(
    session_repo = Depends(get_session_repo),
    llm_service = Depends(get_llm_service),
    memory_service = Depends(get_memory_service)
): ...
```

---

## 19. 异步编程深入

### 19.1 asyncio + threading 混合

本项目同时使用 asyncio 和 threading：
- **asyncio**：FastAPI 请求处理、数据库操作、WebSocket
- **threading**：火山引擎 SDK 的同步流式调用

```python
# 在后台线程运行同步 SDK
thread = threading.Thread(target=run_sync_stream, daemon=True)

# 通过 run_in_executor 将 Queue.get 桥接到 asyncio
chunk = await loop.run_in_executor(None, chunk_queue.get, True, 0.1)
```

### 19.2 异步生成器

大量使用 `AsyncGenerator` 实现流式输出：

```python
async def execute(self, task) -> AsyncGenerator[Dict[str, Any], None]:
    yield {"type": "thinking", "content": "..."}
    yield {"type": "message", "content": "..."}
    yield {"type": "end"}
```

### 19.3 asyncio.Lock 保护共享资源

```python
class MCPClientPool:
    lock = asyncio.Lock()

    async def add_server(self, config):
        async with self.lock:  # 保护连接字典
            self.connections[config.id] = connection
```

### 19.4 并行执行

```python
# 多个 Agent 并行执行
tasks = [agent_registry.call_agent(agent_id, task) for agent_id in agent_ids]
results = await asyncio.gather(*tasks)
```

---

## 20. 部署与扩展

### 20.1 开发环境

```bash
# 安装依赖
pip install -e .

# 启动开发服务器
python main.py
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 20.2 环境配置

创建 `.env` 文件：

```env
VOLCENGINE_API_KEY=your-api-key
VOLCENGINE_MODEL=doubao-seed-2.0-lite-260215
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
WEB_SEARCH_API_KEY=your-search-api-key
DATABASE_URL=sqlite+aiosqlite:///./quest3_agent.db
```

### 20.3 生产部署

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 20.4 扩展方向

1. **新增执行模式**：实现新的 Executor 类，在 chat.py 中注册
2. **新增协作模式**：继承 `BaseCollaborationMode`，在 `CollaborationEngine` 中注册
3. **新增本地工具**：实现工具类，在 main.py 中注册到 `UnifiedToolManager`
4. **新增 MCP 服务器**：通过管理页面或 API 添加，自动连接到 `MCPClientPool`
5. **新增技能**：在 skills 目录创建 skill.md（可选 main.py 入口脚本）
6. **切换 LLM 提供商**：替换 `LLMService` 的实现，保持接口不变
7. **替换向量数据库**：替换 `VectorService` 的实现（如 Milvus、Pinecone）
8. **用户认证**：扩展 `UserService`，添加 JWT/OAuth 支持
9. **前端优化**：React/Vue SPA，实时状态管理

---

## 总结

### 核心学习要点

1. **ReAct + 思维链**：LLM 深度思考 → 工具调用 → 观察 → 循环
2. **统一工具管理**：本地/MCP/技能工具通过 UnifiedToolManager 统一调度
3. **多智能体协作**：4 种协作模式，通过 AgentRegistry 和 A2A 协议通信
4. **记忆系统**：工作记忆 + Agent 长期记忆，重要性衰减 + 语义搜索
5. **流式架构**：全链路流式输出，WebSocket + AsyncGenerator
6. **技能系统**：声明式 skill.md + 可选执行脚本 + GitHub 导入
7. **异步 + 线程桥接**：asyncio 事件循环 + 后台线程处理同步 SDK

### 阅读建议

1. **入门**：从 `app/main.py` 开始，理解服务初始化流程
2. **聊天流程**：阅读 `app/api/chat.py`，理解 WebSocket 事件流
3. **执行引擎**：阅读 `app/core/react_cot_executor.py`，理解 ReAct 循环
4. **工具管理**：阅读 `app/core/tool_manager.py`，理解工具统一调度
5. **协作系统**：阅读 `app/services/collaboration/supervisor.py`，理解多 Agent 协作
6. **记忆系统**：阅读 `app/services/agent_memory_service.py`，理解长期记忆
7. **技能系统**：阅读 `app/skills/registry.py` 和 `app/skills/executor.py`
