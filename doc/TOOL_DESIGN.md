# Quest3 Agent 智能体工具调用系统设计文档

## 版本信息

| 项目 | 内容 |
|------|------|
| 文档版本 | v1.0 |
| 创建日期 | 2026-04-17 |
| 状态 | 待实现 |

---

## 一、文档概述

### 1.1. 目的

本文档描述 Quest3 Agent 智能体工具调用系统的设计方案，包括架构设计、模块划分、接口定义和实现细节。

### 1.2. 范围

本设计涵盖：
- 工具调用决策机制
- 工具执行引擎
- MCP 服务器管理（多服务器支持）
- 前端配置界面
- 用户可见的调用过程展示

---

## 二、需求分析

### 2.1. 核心需求

| 需求编号 | 需求描述 | 优先级 |
|-----------|-----------|---------|
| R1 | LLM 自动决策工具调用方式 | P0 |
| R2 | LLM 决定工具优先级 | P0 |
| R3 | 支持连接多个 MCP 服务器 | P0 |
| R4 | 前端页面配置 MCP 服务器 | P0 |
| R5 | LLM 判断任务复杂度并决策策略 | P0 |
| R6 | 根据任务复杂度动态选择执行策略 | P0 |
| R7 | 暂不考虑权限控制 | P2 |
| R8 | 工具调用失败时智能重试 | P1 |
| R9 | 有限重试次数，失败后告知用户 | P1 |
| R10 | 用户可看到详细工具调用过程 | P1 |
| R11 | 用户不能干预工具调用 | P2 |

### 2.2. 非功能性需求

| 需求 | 描述 |
|------|------|
| 性能 | 工具调用响应时间 < 5s（简单任务）|
| 可靠性 | 系统可用性 > 99% |
| 可扩展性 | 支持无缝添加新工具源 |
| 可维护性 | 模块化设计，职责清晰 |

---

## 三、系统架构

### 3.1. 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     前端层                            │
│  ┌─────────────────────────────────────────────────┐     │
│  │          聊天界面组件                       │     │
│  │  - 消息输入/输出                           │     │
│  │  - 工具调用过程实时展示                     │     │
│  └─────────────────────────────────────────────────┘     │
│  ┌─────────────────────────────────────────────────┐     │
│  │       MCP 服务器配置组件                    │     │
│  │  - 添加/删除服务器                         │     │
│  │  - 查看服务器状态和工具                     │     │
│  │  - 测试连接                               │     │
│  └─────────────────────────────────────────────────┘     │
└───────────────────┬─────────────────────────────────────┘
                    │ WebSocket / HTTP
                    ▼
┌─────────────────────────────────────────────────────────────┐
│                   API 网关层                            │
│  ┌─────────────────────────────────────────────────┐     │
│  │              聊天接口                         │     │
│  │  POST  /api/chat/chat                        │     │
│  │  WS    /api/chat/stream                      │     │
│  └─────────────────────────────────────────────────┘     │
│  ┌─────────────────────────────────────────────────┐     │
│  │             MCP 管理接口                     │     │
│  │  GET   /api/mcp/servers                    │     │
│  │  POST  /api/mcp/servers                    │     │
│  │  DELETE /api/mcp/servers/{id}               │     │
│  │  GET   /api/mcp/servers/{id}/test           │     │
│  └─────────────────────────────────────────────────┘     │
│  ┌─────────────────────────────────────────────────┐     │
│  │            工具调用接口                      │     │
│  │  POST  /api/tools/execute                  │     │
│  │  GET   /api/tools                         │     │
│  └─────────────────────────────────────────────────┘     │
└───────────────────┬─────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│                  智能体引擎层                           │
│  ┌─────────────────────────────────────────────────┐     │
│  │        ToolDecisionEngine 决策引擎           │     │
│  │  - 任务复杂度分析                          │     │
│  │  - 执行策略选择                            │     │
│  │  - 执行计划生成                            │     │
│  └─────────────────────────────────────────────────┘     │
│  ┌─────────────────────────────────────────────────┐     │
│  │      ToolExecutionEngine 执行引擎             │     │
│  │  - 执行工具调用                            │     │
│  │  - 智能重试机制                            │     │
│  │  - 错误处理和恢复                          │     │
│  │  - 执行进度跟踪                            │     │
│  └─────────────────────────────────────────────────┘     │
│  ┌─────────────────────────────────────────────────┐     │
│  │      ToolContextManager 上下文管理          │     │
│  │  - 工具间数据传递                          │     │
│  │  - 执行状态管理                            │     │
│  │  - 历史记录                              │     │
│  └─────────────────────────────────────────────────┘     │
└───────────────────┬─────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│                     工具层                             │
│  ┌──────────────────┐  ┌──────────────────────────┐    │
│  │   本地工具      │  │   MCP 客户端池           │    │
│  │  LocalTools    │  │  MCPClientPool           │    │
│  │ - 文件系统      │  │  - 多服务器连接            │    │
│  │ - 数据库操作    │  │  - 连接池管理            │    │
│  │ - HTTP 请求    │  │  - 负载均衡              │    │
│  │ - 自定义工具    │  └──────────────────────────┘    │
│  └──────────────────┘                               │
│  ┌─────────────────────────────────────────────────┐     │
│  │         ToolRegistry 工具注册表           │     │
│  │  - 统一工具索引                            │     │
│  │  - 工具元数据管理                          │     │
│  │  - 工具发现和注册                          │     │
│  └─────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 3.2. 模块职责

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| ToolDecisionEngine | 分析任务、决策工具、生成计划 | 用户消息、可用工具列表 | 执行计划 |
| ToolExecutionEngine | 执行工具调用、处理重试 | 执行计划、工具注册表 | 执行结果 |
| ToolContextManager | 管理工具上下文和状态 | - | 上下文数据 |
| MCPClientPool | 管理 MCP 服务器连接 | 服务器配置 | 工具列表 |
| LocalTools | 提供本地工具实现 | - | 工具实现 |
| ToolRegistry | 统一管理所有工具 | 工具定义 | 工具索引 |

---

## 四、详细设计

### 4.1. 工具决策引擎 (ToolDecisionEngine)

#### 4.1.1. 职责

1. 分析用户输入，判断任务复杂度
2. 根据复杂度选择执行策略
3. 生成结构化执行计划
4. 支持任务分解和依赖分析

#### 4.1.2. 任务复杂度定义

| 复杂度 | 定义 | 典型场景 | 执行策略 |
|--------|------|----------|----------|
| SIMPLE | 单次工具调用可完成 | 读取文件、列目录、单次 API 调用 | Single |
| MEDIUM | 需要 2-3 步顺序调用 | 读取→分析→保存、多步骤处理 | Chain |
| COMPLEX | 需要多步、条件或并行 | 数据流水线、多源聚合、条件分支 | Mixed |

#### 4.1.3. 执行计划数据结构

```python
class ExecutionPlan:
    """工具执行计划"""

    complexity: ComplexityLevel  # 任务复杂度
    strategy: ExecutionStrategy  # 执行策略
    steps: List[ExecutionStep]  # 执行步骤

class ExecutionStep:
    """单个执行步骤"""

    step_id: str              # 步骤唯一标识
    tool_name: str            # 工具名称
    arguments: Dict           # 工具参数
    depends_on: List[str]     # 依赖的步骤 ID
    parallel: bool           # 是否可并行执行
    retry_on_failure: bool    # 失败是否重试
    max_retries: int         # 最大重试次数
```

#### 4.1.4. 决策流程

```
用户输入
    ↓
LLM 分析任务
    ↓
判断复杂度
    ├─ SIMPLE  → Single 策略
    ├─ MEDIUM  → Chain 策略
    └─ COMPLEX → Mixed 策略
    ↓
生成执行步骤
    ├─ 识别需要的工具
    ├─ 分析步骤依赖
    └─ 优化执行顺序
    ↓
返回执行计划
```

#### 4.1.5. LLM 提示词模板

```
你是一个智能工具调用决策器。请分析用户请求并制定执行计划。

任务类型：
- SIMPLE: 单次工具调用即可完成（如读取文件）
- MEDIUM: 需要 2-3 步顺序调用（如读取+分析+保存）
- COMPLEX: 需要多步、条件判断或并行调用（如复杂数据处理）

执行策略：
- single: 单次调用
- chain: 链式调用（步骤按顺序执行，结果传递）
- parallel: 并行调用（同时执行多个独立步骤）
- mixed: 混合调用（并行+链式组合）

可用工具：
{tools_list}

请返回 JSON 格式执行计划：
{
  "complexity": "SIMPLE|MEDIUM|COMPLEX",
  "strategy": "single|chain|parallel|mixed",
  "description": "任务描述",
  "steps": [
    {
      "step_id": "step_1",
      "tool_name": "tool_name",
      "arguments": {...},
      "depends_on": [],
      "parallel": false,
      "retry_on_failure": true,
      "max_retries": 3
    }
  ]
}
```

### 4.2. 工具执行引擎 (ToolExecutionEngine)

#### 4.2.1. 职责

1. 执行工具调用计划
2. 实现智能重试机制
3. 处理执行错误
4. 跟踪执行进度
5. 流式返回执行状态

#### 4.2.2. 重试策略设计

| 错误类型 | 重试策略 | 重试间隔 | 备用方案 |
|----------|----------|----------|----------|
| NetworkError | 指数退避 | 1s, 2s, 4s | 重试同一工具 |
| TimeoutError | 立即重试 | 0s | 限制重试次数 |
| ParameterError | 参数修正 | - | 让 LLM 重新生成 |
| ToolNotFoundError | 备用工具 | - | 尝试同类工具 |
| PermissionError | 停止执行 | - | 告知用户 |
| UnknownError | 有限重试 | 2s | 标记失败 |

#### 4.2.3. 执行流程

```
接收执行计划
    ↓
初始化执行上下文
    ↓
按拓扑顺序执行步骤
    ↓
    检查步骤依赖
    ├─ 未满足 → 等待
    └─ 已满足 → 执行
        ↓
    执行工具调用
        ├─ 成功
        │   ├─ 保存结果到上下文
        │   └─ 推送进度
        └─ 失败
            ├─ 判断错误类型
            ├─ 应用重试策略
            ├─ 重试次数 < 上限？
            │   ├─ 是 → 重试
            │   └─ 否 → 标记失败，继续或停止
            └─ 所有步骤失败？
                ├─ 是 → 返回失败，告知用户
                └─ 否 → 继续其他步骤
    ↓
返回执行结果
```

#### 4.2.4. 执行状态流

执行引擎通过 WebSocket 流式推送状态：

```json
// 开始执行
{
  "type": "execution_start",
  "plan_id": "uuid",
  "total_steps": 3
}

// 思考阶段
{
  "type": "thinking",
  "message": "分析任务复杂度..."
}

// 步骤开始
{
  "type": "step_start",
  "step_id": "step_1",
  "step_number": 1,
  "total_steps": 3,
  "tool_name": "read_file",
  "arguments": {"file_path": "README.md"}
}

// 步骤执行中
{
  "type": "step_progress",
  "step_id": "step_1",
  "message": "正在读取文件..."
}

// 步骤成功
{
  "type": "step_complete",
  "step_id": "step_1",
  "success": true,
  "result_preview": "已读取 1024 字符",
  "result": "完整结果"
}

// 步骤失败
{
  "type": "step_error",
  "step_id": "step_2",
  "error": "工具执行失败",
  "retrying": true,
  "retry_count": 1
}

// 执行完成
{
  "type": "execution_complete",
  "success": true,
  "final_result": "..."
}
```

### 4.3. MCP 服务器管理

#### 4.3.1. 数据结构

```python
class MCPServerConfig:
    """MCP 服务器配置"""

    id: str                  # 服务器唯一标识
    name: str                # 服务器名称
    url: str                 # 服务器 URL
    description: str          # 服务器描述
    status: ConnectionStatus   # 连接状态
    tool_count: int          # 提供的工具数量
    added_at: datetime       # 添加时间
    last_connected: datetime # 最后连接时间
    priority: int           # 优先级（数字越小越高）

class MCPServerConnection:
    """MCP 服务器连接"""

    config: MCPServerConfig
    client: MCPClient        # MCP 客户端
    tools: Dict[str, Tool]  # 工具列表
    health_check_interval: int  # 健康检查间隔（秒）
```

#### 4.3.2. 连接池管理

```python
class MCPClientPool:
    """MCP 客户端连接池"""

    connections: Dict[str, MCPServerConnection]  # 服务器ID → 连接

    async def connect_server(self, config: MCPServerConfig) -> bool
    async def disconnect_server(self, server_id: str) -> bool
    async def get_all_tools(self) -> Dict[str, Tool]
    async def execute_tool(self, tool_name: str, args: Dict) -> Any
    async def health_check(self, server_id: str) -> bool
    async def reconnect_all(self) -> None
```

#### 4.3.3. 工具命名冲突处理

当多个服务器提供同名工具时，添加服务器前缀：

```python
# 示例
Server A 提供: search_files
Server B 提供: search_files

# 聚合后
{
  "serverA_search_files": Tool(...),
  "serverB_search_files": Tool(...)
}
```

### 4.4. 工具注册表 (ToolRegistry)

#### 4.4.1. 设计

```python
class ToolRegistry:
    """统一工具注册表"""

    local_tools: Dict[str, Tool]
    mcp_tools: Dict[str, Tool]

    def register_tool(self, tool: Tool) -> None
    def get_tool(self, name: str) -> Optional[Tool]
    def list_all_tools(self) -> List[Tool]
    def search_tools(self, keyword: str) -> List[Tool]
    def get_tool_schema(self) -> Dict  # 用于 LLM
```

#### 4.4.2. 工具元数据

```python
class Tool:
    """工具定义"""

    name: str
    display_name: str       # 显示名称
    description: str       # 工具描述
    category: str         # 分类
    source: ToolSource     # 来源（local/mcp）
    server_id: Optional[str]  # 所属服务器（MCP）
    input_schema: Dict    # 参数 schema
    output_schema: Dict   # 输出 schema
    handler: Callable     # 执行函数（本地工具）
```

---

## 五、接口设计

### 5.1. RESTful API

#### 5.1.1. MCP 服务器管理

```
GET /api/mcp/servers
描述：获取所有 MCP 服务器
响应：
{
  "servers": [
    {
      "id": "uuid",
      "name": "阿里云 MCP",
      "url": "https://aliyun-mcp.com",
      "description": "提供文件处理和数据分析工具",
      "status": "connected",
      "tool_count": 15,
      "priority": 1
    }
  ]
}

POST /api/mcp/servers
描述：添加 MCP 服务器
请求体：
{
  "name": "服务器名称",
  "url": "https://example.com",
  "description": "描述",
  "priority": 1
}
响应：
{
  "success": true,
  "server_id": "uuid",
  "message": "服务器已添加"
}

DELETE /api/mcp/servers/{id}
描述：删除 MCP 服务器
响应：
{
  "success": true,
  "message": "服务器已删除"
}

GET /api/mcp/servers/{id}/test
描述：测试服务器连接
响应：
{
  "success": true,
  "connected": true,
  "latency_ms": 150,
  "tool_count": 15
}

GET /api/mcp/servers/{id}/tools
描述：获取服务器提供的工具
响应：
{
  "server_id": "uuid",
  "tools": [...]
}
```

#### 5.1.2. 工具调用

```
GET /api/tools
描述：获取所有可用工具
响应：
{
  "total": 25,
  "local_tools": 3,
  "mcp_tools": 22,
  "tools": [...]
}

POST /api/tools/dry-run
描述：模拟执行（生成计划但不执行）
请求体：
{
  "message": "用户消息",
  "session_id": "uuid"
}
响应：
{
  "plan": {...}
}
```

### 5.2. WebSocket API

#### 5.2.1. 工具执行流

```
WS /api/chat/stream

客户端发送：
{
  "type": "execute",
  "message": "用户消息",
  "session_id": "uuid"
}

服务器流式推送：
{
  "type": "thinking|step_start|step_progress|step_complete|...",
  ...
}
```

---

## 六、前端设计

### 6.1. 页面结构

```
主页面
├── 聊天区域
│   ├── 消息列表
│   ├── 输入框
│   └── 工具调用过程面板
├── 侧边栏
│   ├── 历史会话列表
│   └── MCP 服务器管理入口
└── MCP 管理弹窗
    ├── 服务器列表
    ├── 添加按钮
    └── 服务器详情
```

### 6.2. 工具调用过程展示

#### 6.2.1. 组件设计

```html
<ToolExecutionPanel>
  <ThinkingStage>
    显示 LLM 思考过程
  </ThinkingStage>

  <ExecutionSteps>
    <StepCard>
      <StepHeader>
        步骤编号、工具名称
      </StepHeader>
      <StepArguments>
        工具参数（可展开）
      </StepArguments>
      <StepStatus>
        执行中 / 成功 / 失败
      </StepStatus>
      <StepResult>
        结果预览（可展开）
      </StepResult>
    </StepCard>
  </ExecutionSteps>

  <FinalResult>
    最终响应
  </FinalResult>
</ToolExecutionPanel>
```

#### 6.2.2. 展示示例

```
[思考] 分析任务复杂度...
[判断] 这是一个中等复杂度任务，采用链式调用策略

╔════════════════════════════════════════════╗
║  执行步骤 1/3                           ║
╠════════════════════════════════════════════╣
║  工具: read_file                          ║
║  参数:                                     ║
║    {                                        ║
║      "file_path": "README.md"                ║
║    }                                        ║
║  状态: ✓ 成功                            ║
║  结果: 已读取 1024 字符                    ║
╚════════════════════════════════════════════╝

╔════════════════════════════════════════════╗
║  执行步骤 2/3                           ║
╠════════════════════════════════════════════╣
║  工具: analyze_text (来自: 阿里云MCP)      ║
║  参数:                                     ║
║    {                                        ║
║      "text": "...",                          ║
║      "mode": "summary"                       ║
║    }                                        ║
║  状态: ⏳ 执行中...                       ║
╚════════════════════════════════════════════╝

[完成] 任务执行完毕
```

### 6.3. MCP 管理界面

```
MCP 服务器管理
┌─────────────────────────────────────────────┐
│ [+ 添加服务器]                      │
├─────────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐   │
│ │ 阿里云 MCP            [🟢 已连接]│   │
│ │ https://aliyun-mcp.com            │   │
│ │ 工具数: 15                      │   │
│ │ [查看工具] [删除] [测试连接]      │   │
│ └─────────────────────────────────────┘   │
│                                     │
│ ┌─────────────────────────────────────┐   │
│ │ 本地测试              [🔴 未连接]│   │
│ │ http://localhost:8080             │   │
│ │ [连接] [删除]                    │   │
│ └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## 七、数据流设计

### 7.1. 完整执行流程

```
1. 用户输入消息
   ↓
2. [WebSocket] 发送给后端
   ↓
3. [ToolDecisionEngine]
   ├─ 获取可用工具列表
   ├─ LLM 分析任务
   ├─ 判断复杂度
   ├─ 选择执行策略
   └─ 生成执行计划
   ↓
4. [WebSocket] 推送: 执行计划
   ↓
5. [ToolExecutionEngine]
   ├─ 初始化上下文
   ├─ 按步骤执行
   │   ├─ 执行工具
   │   │   ├─ 成功 → 保存结果
   │   │   └─ 失败 → 应用重试策略
   │   └─ 推送进度
   └─ 汇总结果
   ↓
6. [WebSocket] 推送: 最终结果
   ↓
7. 前端展示响应
```

### 7.2. 错误处理流程

```
工具调用失败
   ↓
判断错误类型
   ├─ NetworkError
   │   └─ 指数退避重试
   ├─ TimeoutError
   │   └─ 立即重试（有限次数）
   ├─ ParameterError
   │   ├─ 传递给 LLM 重新生成参数
   │   └─ 用新参数重试
   ├─ ToolNotFoundError
   │   ├─ 搜索备用工具
   │   └─ 用备用工具重试
   ├─ PermissionError
   │   └─ 停止执行，告知用户
   └─ UnknownError
       └─ 有限次重试后标记失败

达到重试上限
   ├─ 此步骤失败
   ├─ 检查是否关键步骤
   │   ├─ 是 → 停止整个执行
   │   └─ 否 → 继续其他步骤
   └─ 通知用户执行结果
```

---

## 八、数据库设计

### 8.1. MCP 服务器表

```sql
CREATE TABLE mcp_servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT,
    priority INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT true,
    added_at TIMESTAMP,
    last_connected TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### 8.2. 工具调用历史表（可选）

```sql
CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    tool_name TEXT NOT NULL,
    tool_source TEXT,  -- local/mcp
    server_id TEXT,
    arguments TEXT,  -- JSON
    result TEXT,  -- JSON
    status TEXT,  -- success/failed
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP
);
```

---

## 九、安全考虑

### 9.1. 当前不实现（按需求）

- [ ] 权限控制
- [ ] 操作审计
- [ ] 敏感操作确认

### 9.2. 未来增强建议

- 工具白名单/黑名单
- 操作日志和审计
- 关键操作二次确认
- 工具调用速率限制
- 输入参数验证和清理

---

## 十、测试策略

### 10.1. 单元测试

- [ ] ToolDecisionEngine 测试
  - LLM 决策测试
  - 复杂度判断测试
  - 计划生成测试

- [ ] ToolExecutionEngine 测试
  - 重试机制测试
  - 错误处理测试
  - 并行执行测试

- [ ] MCPClientPool 测试
  - 连接管理测试
  - 工具聚合测试
  - 健康检查测试

### 10.2. 集成测试

- [ ] 端到端工具调用测试
- [ ] 多 MCP 服务器集成测试
- [ ] 流式推送测试

### 10.3. 性能测试

- [ ] 并发工具调用性能
- [ ] MCP 连接池性能
- [ ] 大量工具场景性能

---

## 十一、实施计划

### Phase 1: 基础增强 (1-2 周)

| 任务 | 优先级 | 估时 |
|------|---------|------|
| ToolExecutionEngine 实现 | P0 | 3d |
| 智能重试机制 | P0 | 2d |
| 执行状态流式推送 | P1 | 2d |
| 前端工具过程展示 | P1 | 3d |

### Phase 2: 决策能力 (1-2 周)

| 任务 | 优先级 | 估时 |
|------|---------|------|
| ToolDecisionEngine 实现 | P0 | 4d |
| 复杂度判断 | P0 | 2d |
| 执行计划数据结构 | P0 | 1d |
| LLM 提示词优化 | P1 | 2d |

### Phase 3: MCP 管理 (1 周)

| 任务 | 优先级 | 估时 |
|------|---------|------|
| MCPClientPool 实现 | P0 | 3d |
| 数据库表和模型 | P0 | 1d |
| MCP 管理 API | P0 | 2d |
| 前端配置页面 | P1 | 3d |

### Phase 4: 高级特性 (1-2 周)

| 任务 | 优先级 | 估时 |
|------|---------|------|
| 并行执行支持 | P2 | 3d |
| 条件分支执行 | P2 | 2d |
| 工具依赖链 | P2 | 3d |
| 性能优化 | P2 | 2d |

---

## 十二、附录

### A. 术语表

| 术语 | 定义 |
|------|------|
| MCP | Model Context Protocol，模型上下文协议 |
| LLM | Large Language Model，大语言模型 |
| 执行计划 | 工具调用的结构化步骤描述 |
| 复杂度 | 任务执行所需的资源规模和复杂程度 |
| 重试策略 | 工具调用失败后的恢复方案 |
| 工具注册表 | 所有可用工具的统一索引 |

### B. 参考文档

- [Anthropic MCP 规范](https://spec.modelcontextprotocol.io/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [WebSocket 协议](https://websockets.readthedocs.io/)

---

**文档结束**
