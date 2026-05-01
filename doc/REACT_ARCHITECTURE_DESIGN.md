# Quest3 Agent 技术方案 - ReAct模式与智能体管理

## 1. 概述

本文档描述了Quest3 Agent系统的扩展架构设计，主要包含：

1. **保留并增强现有的Plan模式** - 基于LLM的提前规划执行
2. **新增ReAct模式** - 思考(Thought)-行动(Action)-观察(Observation)循环模式
3. **智能体管理系统** - 支持创建、配置、管理多个智能体
4. **智能体执行策略选择** - 可配置不同执行模式
5. **工具和MCP精细化管理** - 智能体级别的工具/MCP访问控制

## 2. 核心概念

### 2.1 执行模式

#### Plan模式（现有）
- **特点**：LLM预先分析任务，生成完整执行计划，然后按计划执行
- **适用场景**：复杂、多步骤的确定性任务
- **优势**：可预览执行步骤，便于用户理解和确认
- **劣势**：需要额外LLM调用进行规划，灵活性相对较低

#### ReAct模式（新增）
- **特点**：LLM通过"思考→行动→观察"的循环逐步完成任务
- **适用场景**：探索性任务、需要动态决策的场景
- **优势**：高度灵活，可基于观察动态调整策略
- **劣势**：无法预览全部步骤，可能需要更多LLM调用

### 2.2 智能体(Agent)

智能体是具有特定角色和能力的AI助手，包含：

- **基本属性**：名称、描述、类型（聊天/编码/研究/自定义）
- **LLM配置**：模型选择、温度、最大token数
- **执行策略**：Plan模式或ReAct模式
- **工具配置**：可访问的MCP服务器列表、工具权限配置
- **系统提示词**：个性化的行为指令
- **统计信息**：使用次数、成功率等

## 3. 系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                         前端层                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ 聊天界面  │  │Agent管理  │  │ MCP管理  │          │
│  └─────┬────┘  └──────────┘  └──────────┘          │
└────────┼──────────────────────────────────────────────────┘
         │ WebSocket/HTTP API
┌────────┼──────────────────────────────────────────────────┐
│         │              API层                             │
│  ┌─────▼──────────────────────────────────────────┐    │
│  │    AgentService                               │    │
│  │    - selectBestAgent()                        │    │
│  │    - create/update/delete/list()               │    │
│  └───────────────────────────────────────────────────┘    │
│  ┌─────▼──────────────────────────────────────────┐    │
│  │    ChatService (WebSocket)                    │    │
│  │    - stream_chat()                           │    │
│  │    - 选择Agent → 执行策略路由                  │    │
│  └───────────────────────────────────────────────────┘    │
└────────┼──────────────────────────────────────────────────┘
         │
┌────────▼──────────────────────────────────────────────────┐
│                    服务层                               │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │AgentService│  │PlanMode    │  │ReActMode   │    │
│  │            │  │Executor    │  │Executor    │    │
│  └────────────┘  └────────────┘  └────────────┘    │
│                                                       │
│  ┌────────────┐  ┌────────────┐                    │
│  │LLMService  │  │MCPService  │                    │
│  │            │  │            │                    │
│  └────────────┘  └────────────┘                    │
└────────┼──────────────────────────────────────────────────┘
         │
┌────────▼──────────────────────────────────────────────────┐
│                    数据层                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │Agents表   │  │Sessions表 │  │Messages表 │       │
│  │           │  │           │  │           │       │
│  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心组件设计

#### 3.2.1 Agent（智能体）

**数据模型**：
```python
class Agent:
    id: str
    name: str
    description: str
    type: AgentType  # CHAT, CODER, RESEARCHER, CUSTOM
    system_prompt: str
    model: str
    temperature: float
    max_tokens: int
    execution_mode: ExecutionMode  # PLAN, REACT
    mcp_servers: List[AgentMCPServer]
    tools: List[AgentToolConfig]
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime
    usage_count: int
```

**数据库表结构**：
```sql
-- 智能体表
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    type TEXT DEFAULT 'custom',
    system_prompt TEXT,
    model TEXT,
    temperature REAL,
    max_tokens INTEGER,
    execution_mode TEXT DEFAULT 'plan',  -- 'plan' or 'react'
    enabled INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    usage_count INTEGER DEFAULT 0
);

-- 智能体-MCP服务器关联表
CREATE TABLE agent_mcp_servers (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    server_id TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

-- 智能体工具配置表
CREATE TABLE agent_tools (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    permission TEXT DEFAULT 'optional',  -- 'required', 'optional', 'forbidden'
    description TEXT,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
```

#### 3.2.2 Plan模式执行器（已实现，需增强）

**执行流程**：
```
1. 分析任务 → DecisionEngine.analyze_task()
2. 生成执行计划 → ExecutionPlan
3. 展示计划给用户（可选）
4. 执行计划 → ExecutionEngine.execute_plan()
5. 生成最终回复 → LLMService
```

**增强点**：
- 支持Agent级别的工具过滤
- 支持Agent级别的系统提示词
- 支持执行进度事件流式输出

#### 3.2.3 ReAct模式执行器（新增）

**核心概念**：
- **Thought(思考)**：LLM分析当前状态，决定下一步行动
- **Action(行动)**：调用工具执行特定操作
- **Observation(观察)**：工具执行的结果反馈给LLM

**执行流程**：
```
初始化:
  - 收集可用工具（根据Agent配置过滤）
  - 构建系统提示词

循环 (max_steps次):
  1. Thought阶段:
     - LLM分析当前状态和任务
     - 决定：调用工具、完成任务或继续思考

  2. Action阶段 (如果决定调用工具):
     - 调用指定工具
     - 记录到执行历史

  3. Observation阶段:
     - 获取工具执行结果
     - 格式化为观察文本
     - 添加到对话历史

  4. 检查完成条件:
     - 如果LLM表示任务完成 → 退出循环
     - 如果达到最大步数 → 退出循环

最终回复:
  - 基于执行历史生成总结性回复
```

**ReAct提示词模板**：
```
你是一个智能助手，需要通过"思考→行动→观察"的循环来完成任务。

当前任务: {task}

可用工具:
{tools_description}

执行历史:
{execution_history}

请按以下格式回复：
思考: [你的思考过程]
行动: 工具名称|参数1=值1,参数2=值2

或当任务完成时:
思考: [你的思考过程]
完成: [最终回复]
```

**实现类结构**：
```python
class ReActExecutor:
    """ReAct模式执行器"""

    def __init__(self, agent_config: Agent):
        self.agent_config = agent_config
        self.llm_service = LLMService()
        self.max_steps = 10  # 最大循环次数
        self.execution_history = []

    async def execute(
        self,
        task: str,
        conversation_history: List[Dict]
    ) -> AsyncGenerator[Dict, None]:
        """执行ReAct循环

        Args:
            task: 用户任务
            conversation_history: 对话历史

        Yields:
            执行事件
        """
        # 获取可用工具
        available_tools = self._get_filtered_tools()

        for step in range(self.max_steps):
            # 构建上下文
            context = self._build_context(
                task,
                self.execution_history,
                conversation_history
            )

            # Thought阶段
            yield self._emit("thinking", "分析当前状态...")
            thought_response = await self._llm_think(context)

            # 解析LLM响应
            action = self._parse_action(thought_response)

            if action.type == "complete":
                # 任务完成
                yield self._emit("complete", action.message)
                break

            elif action.type == "tool_call":
                # Action阶段
                yield self._emit("action_start", {
                    "tool_name": action.tool_name,
                    "arguments": action.arguments
                })

                # 执行工具
                try:
                    result = await self._call_tool(
                        action.tool_name,
                        action.arguments
                    )

                    # Observation阶段
                    yield self._emit("observation", {
                        "tool_name": action.tool_name,
                        "result": self._format_result(result)
                    })

                    # 记录到历史
                    self.execution_history.append({
                        "step": step + 1,
                        "thought": action.thought,
                        "action": {
                            "tool": action.tool_name,
                            "arguments": action.arguments
                        },
                        "observation": str(result)
                    })

                except Exception as e:
                    yield self._emit("error", str(e))
                    self.execution_history.append({
                        "step": step + 1,
                        "thought": action.thought,
                        "action": {
                            "tool": action.tool_name,
                            "arguments": action.arguments
                        },
                        "observation": f"错误: {str(e)}"
                    })

    def _get_filtered_tools(self) -> Dict[str, Any]:
        """根据Agent配置过滤工具"""
        # 只返回Agent允许的工具
        pass

    def _build_context(
        self,
        task: str,
        history: List[Dict],
        conversation: List[Dict]
    ) -> str:
        """构建ReAct提示上下文"""
        pass

    async def _llm_think(self, context: str) -> str:
        """LMM思考阶段"""
        pass

    def _parse_action(self, response: str) -> ReActAction:
        """解析LLM响应为行动"""
        pass
```

#### 3.2.4 执行策略路由器

**统一入口**：
```python
class ExecutionStrategyRouter:
    """执行策略路由器"""

    def __init__(self):
        self.plan_executor = PlanExecutor()
        self.react_executor = ReActExecutor()

    async def execute(
        self,
        agent: Agent,
        task: str,
        conversation_history: List[Dict]
    ) -> AsyncGenerator[Dict, None]:
        """根据Agent配置路由到对应执行器

        Args:
            agent: 智能体配置
            task: 用户任务
            conversation_history: 对话历史

        Yields:
            执行事件流
        """
        if agent.execution_mode == "plan":
            async for event in self.plan_executor.execute(
                agent, task, conversation_history
            ):
                yield event

        elif agent.execution_mode == "react":
            async for event in self.react_executor.execute(
                agent, task, conversation_history
            ):
                yield event

        else:
            raise ValueError(f"Unknown execution mode: {agent.execution_mode}")
```

## 4. API设计

### 4.1 Agent管理API

```python
# 列出所有智能体
GET /api/agents
Response:
{
  "agents": [Agent]
}

# 创建智能体
POST /api/agents
Request:
{
  "name": "Python代码助手",
  "description": "帮助编写和调试代码",
  "type": "coder",
  "execution_mode": "react",
  "mcp_servers": ["server_id1", "server_id2"],
  "tools": [
    {"tool_name": "execute_code", "permission": "required"}
  ],
  "system_prompt": "你是一个专业的Python程序员..."
}
Response: Agent

# 获取智能体详情
GET /api/agents/{agent_id}
Response: Agent

# 更新智能体
PUT /api/agents/{agent_id}
Request: AgentUpdate
Response: Agent

# 删除智能体
DELETE /api/agents/{agent_id}
Response: {"success": true}

# 选择最佳智能体
POST /api/agents/select
Request:
{
  "message": "用户消息",
  "conversation_history": [...]
}
Response:
{
  "agent": Agent,
  "reason": "选择该智能体的原因"
}
```

### 4.2 聊天API（WebSocket）

```python
WebSocket /api/chat/stream

初始消息:
{
  "session_id": "uuid",
  "agent_id": "uuid",  # 新增：指定智能体
  "message": "用户消息"
}

事件流（增强）:
{
  "type": "thinking",
  "message": "思考中..."
}

{
  "type": "planning",  # Plan模式
  "plan": {...}
}

{
  "type": "thought",  # ReAct模式
  "step": 1,
  "content": "我需要先读取文件..."
}

{
  "type": "action_start",  # ReAct模式
  "tool_name": "read_file",
  "arguments": {"file_path": "data.txt"}
}

{
  "type": "observation",  # ReAct模式
  "result": "文件内容..."
}

{
  "type": "step_start",  # Plan模式
  "step_id": "step_1",
  "step_number": 1,
  "total_steps": 3
}

{
  "type": "message",
  "content": "最终回复..."
}

{
  "type": "done"
}
```

## 5. 前端实现

### 5.1 Agent管理界面

**页面路由**：`/static/agent_manager.html`（新建页面）

**界面布局**：
```
┌─────────────────────────────────────────────────────────┐
│  Agent管理                                    [+ 新建] │
├─────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐       │
│  │ Python  │  │ 研究   │  │ 通用   │  ...     │
│  │ 助手    │  │ 助手    │  │ 助手    │         │
│  │ Plan    │  │ ReAct   │  │ Plan    │         │
│  │ 128次   │  │ 45次    │  │ 1.2k次  │         │
│  │ [编辑]  │  │ [编辑]  │  │ [编辑]  │         │
│  │ [删除]  │  │ [删除]  │  │ [删除]  │         │
│  └─────────┘  └─────────┘  └─────────┘       │
└─────────────────────────────────────────────────────────┘
```

**功能列表**：
1. **智能体列表展示**
   - 卡片式展示每个Agent
   - 显示：名称、类型、执行模式、使用次数、状态（启用/禁用）
   - 支持按使用次数、优先级排序

2. **创建智能体**
   - 点击"新建"按钮打开创建表单
   - 表单字段详见下方

3. **编辑智能体**
   - 点击Agent卡片上的"编辑"按钮
   - 打开编辑表单，预填充当前配置

4. **删除智能体**
   - 点击"删除"按钮
   - 弹出确认对话框
   - 确认后调用DELETE API

5. **启用/禁用智能体**
   - 切换开关控制Agent是否可用

**Agent配置表单**：

```
┌─────────────────────────────────────────────────────────────┐
│  Agent配置                             [保存] [取消]  │
├─────────────────────────────────────────────────────────────┤
│                                                      │
│  基本信息                                             │
│  ─────────────────────────────────────────────────────   │
│  名称: [________________]                              │
│  描述: [_______________________________]                │
│  类型: [聊天 ▼] [编码] [研究] [自定义]                │
│  优先级: [___] (数字越高优先级越高）                     │
│  启用: [✓]                                           │
│                                                      │
│  执行配置                                             │
│  ─────────────────────────────────────────────────────   │
│  执行模式: [⦿ Plan模式] [○ ReAct模式]                 │
│                                                      │
│  LLM参数                                             │
│  ─────────────────────────────────────────────────────   │
│  模型: [claude-3-5-sonnet-20241022 ▼]            │
│  温度: [0.7]                                          │
│  最大token: [4096]                                      │
│                                                      │
│  MCP服务器                                            │
│  ─────────────────────────────────────────────────────   │
│  可用MCP服务器:                                       │
│  ☑ 代码解释器 (streamable)                             │
│  ☑ 文件系统 (local)                                  │
│  ☐ 自定义MCP 1                                        │
│                                                      │
│  工具权限                                             │
│  ─────────────────────────────────────────────────────   │
│  execute_code: [必需 ▼] [可选] [禁止]                  │
│  read_file:    [可选]                                  │
│  write_file:   [禁止]                                  │
│  list_directory:[可选]                                  │
│                                                      │
│  系统提示词                                           │
│  ─────────────────────────────────────────────────────   │
│  ┌────────────────────────────────────────────────────┐ │
│  │ 你是一个专业的[角色]助手...                        │ │
│  │ ...                                              │ │
│  │ (支持多行编辑）                                   │ │
│  └────────────────────────────────────────────────────┘ │
│  [使用模板] [重置为默认]                              │
│                                                      │
└─────────────────────────────────────────────────────────────┘
```

**表单字段详细说明**：

| 字段 | 类型 | 必填 | 说明 | 默认值 |
|-----|------|------|------|--------|
| name | 文本 | ✓ | Agent名称 | - |
| description | 文本 | ✓ | Agent功能描述 | - |
| type | 选择 | ✓ | Agent类型 | custom |
| priority | 数字 | ✗ | 自动选择时的优先级 | 0 |
| enabled | 布尔 | ✗ | 是否启用 | true |
| execution_mode | 选择 | ✓ | 执行模式 | plan |
| model | 选择 | ✗ | LLM模型 | 使用全局默认 |
| temperature | 浮点 | ✗ | 温度参数 | 使用全局默认 |
| max_tokens | 整数 | ✗ | 最大token数 | 使用全局默认 |
| mcp_servers | 多选 | ✗ | MCP服务器列表 | [] |
| tools | 对象数组 | ✗ | 工具权限配置 | [] |
| system_prompt | 多行文本 | ✗ | 系统提示词 | 根据类型生成默认 |

**API调用示例**：

```javascript
// 创建Agent
async function createAgent(formData) {
  const response = await fetch('/api/agents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: formData.name,
      description: formData.description,
      type: formData.type,
      execution: 'plan', // 或 'react'
      priority: parseInt(formData.priority) || 0,
      enabled: true,
      model: formData.model || null,
      temperature: formData.temperature || null,
      max_tokens: formData.maxTokens || null,
      mcp_servers: formData.mcpServers || [],
      tools: formData.tools || [],
      system_prompt: formData.systemPrompt || ''
    })
  });
  return await response.json();
}

// 更新Agent
async function updateAgent(agentId, formData) {
  const response = await fetch(`/api/agents/${agentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  });
  return await response.json();
}

// 删除Agent
async function deleteAgent(agentId) {
  if (!confirm('确定要删除此Agent吗？')) return;

  const response = await fetch(`/api/agents/${agentId}`, {
    method: 'DELETE'
  });
  return await response.json();
}

// 加载Agent列表
async function loadAgents() {
  const response = await fetch('/api/agents');
  const data = await response.json();
  return data.agents;
}

// 加载MCP服务器列表（用于Agent配置）
async function loadMCPServers() {
  const response = await fetch('/api/mcp/servers');
  const data = await response.json();
  return data.servers;
}

// 加载可用工具列表（用于Agent配置）
async function loadAvailableTools() {
  const response = await fetch('/tools');
  const data = await response.json();
  return data.tools;
}
```

### 5.2 聊天界面Agent选择

**界面布局增强**：

在聊天界面头部添加Agent选择器：

```
┌─────────────────────────────────────────────────────────────┐
│  Quest3 Agent                                  [新建Agent]│
├─────────────────────────────────────────────────────────────┤
│  ┌────────────────────┐  ┌──────────────────────────┐  │
│  │ 会话列表          │  │ 聊天区域                │  │
│  │                   │  │                          │  │
│  │ [会话1]          │  │ Agent选择: [默认 ⬎]    │  │
│  │ [会话2]          │  │ ┌───────────────────────┐ │  │
│  │ ...              │  │ │ [用户消息]            │ │  │
│  │ [+ 新建]          │  │ │ [AI回复]             │ │  │
│  │                   │  │ │ ...                  │ │  │
│  └───────────────────┘  │ └───────────────────────┘ │  │
│                          │ [输入框...] [发送]      │  │
│                          └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Agent选择下拉框设计**：

```javascript
// Agent选择器组件
class AgentSelector {
  constructor() {
    this.agents = [];
    this.currentAgent = null;
    this.selector = null;
  }

  async init() {
    // 加载Agent列表
    this.agents = await this.loadAgents();

    // 创建下拉框
    this.createSelector();

    // 绑定变化事件
    this.selector.addEventListener('change', (e) => {
      this.onAgentChange(e.target.value);
    });
  }

  createSelector() {
    const container = document.querySelector('.chat-header');

    const wrapper = document.createElement('div');
    wrapper.className = 'agent-selector-wrapper';

    const label = document.createElement('label');
    label.textContent = 'Agent: ';

    this.selector = document.createElement('select');
    this.selector.className = 'agent-selector';

    // 添加默认选项（不指定Agent）
    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = '默认（自动选择）';
    this.selector.appendChild(defaultOption);

    // 添加Agent选项
    this.agents.forEach(agent => {
      const option = document.createElement('option');
      option.value = agent.id;
      option.textContent = `${agent.name} (${agent.type})`;
      option.dataset.mode = agent.execution_mode;
      this.selector.appendChild(option);
    });

    wrapper.appendChild(label);
    wrapper.appendChild(this.selector);

    // 添加"新建"按钮
    const newAgentBtn = document.createElement('button');
    newAgentBtn.textContent = '+';
    newAgentBtn.className = 'new-agent-btn';
    newAgentBtn.title = '新建Agent';
    newAgentBtn.onclick = () => window.location.href = '/static/agent_manager.html';
    wrapper.appendChild(newAgentBtn);

    container.appendChild(wrapper);
  }

  async onAgentChange(agentId) {
    this.currentAgent = this.agents.find(a => a.id === agentId);

    // 更新WebSocket连接
    if (ws && ws.readyState === WebSocket.OPEN) {
      await this.reconnectWithAgent(agentId);
    } else {
      // 保存选择的Agent ID，连接时使用
      this.selectedAgentId = agentId;
    }
  }

  async reconnectWithAgent(agentId) {
    // 断开现有连接
    if (ws) {
      ws.close();
    }

    // 重新连接并指定Agent
    await connectWebSocket(agentId);
  }

  async loadAgents() {
    const response = await fetch('/api/agents?enabled_only=true');
  const data = await response.json();
    return data.agents;
  }
}

// 全局实例
const agentSelector = new AgentSelector();
```

**WebSocket连接时传递Agent ID**：

```javascript
async function connectWebSocket(selectedAgentId = null) {
  const sessionId = getCurrentSessionId();

  if (!sessionId) {
    alert('请先选择或创建一个会话');
    return;
  }

  const ws = new WebSocket('ws://localhost:8000/api/chat/stream');

  ws.onopen = async () => {
    // 发送初始消息，包含agent_id
    const initialMessage = {
      session_id: sessionId
    };

    if (selectedAgentId) {
      initialMessage.agent_id = selectedAgentId;
    }

    ws.send(JSON.stringify(initialMessage));
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'connected') {
      // 连接成功，显示Agent信息
      if (data.agent) {
        showActiveAgent(data.agent);
      } else {
        showDefaultAgent();
      }
      enableChat(true);
    }
    // ... 其他消息处理
  };
}
```

**显示当前活跃Agent信息**：

```javascript
function showActiveAgent(agent) {
  const agentInfo = document.querySelector('.active-agent-info');

  if (!agentInfo) {
    agentInfo = document.createElement('div');
    agentInfo.className = 'active-agent-info';
    document.querySelector('.chat-header').appendChild(agentInfo);
  }

  // 根据执行模式显示不同图标
  const modeIcon = agent.execution_mode === 'react' ? '🔄' : '📋';

  agentInfo.innerHTML = `
    <span class="agent-icon">${modeIcon}</span>
    <span class="agent-name">${agent.name}</span>
    <span class="agent-type">(${agent.type})</span>
    <span class="agent-mode">[${agent.execution_mode}]</span>
  `;
}

function showDefaultAgent() {
  const agentInfo = document.querySelector('.active-agent-info');
  if (agentInfo) {
    agentInfo.innerHTML = '使用默认Agent';
  }
}
```

**Agent选择相关CSS**：

```css
.agent-selector-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 20px;
}

.agent-selector {
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(0, 0, 0, 0.1);
  border-radius: 16px;
  padding: 6px 12px;
  font-size: 14px;
  min-width: 150px;
  cursor: pointer;
}

.new-agent-btn {
  background: #667eea;
  color: white;
  border: none;
  border-radius: 50%;
  width: 28px;
  height: 28px;
  font-size: 18px;
  cursor: pointer;
  transition: background 0.3s;
}

.new-agent-btn:hover {
  background: #764ba2;
}

.active-agent-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  background: rgba(102, 126, 234, 0.2);
  border-radius: 16px;
  font-size: 13px;
  margin-top: 8px;
}

.agent-icon {
  font-size: 16px;
}

.agent-name {
  font-weight: 500;
}

.agent-type {
  color: rgba(0, 0, 0, 0.6);
}

.agent-mode {
  background: rgba(0, 0, 0, 0.1);
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  text-transform: uppercase;
}
```

### 5.3 页面导航设计

**添加Agent管理入口**：

1. 在聊天界面添加"Agent管理"按钮
2. 在MCP管理页面添加"Agent管理"链接
3. 可以从主页直接访问 `/static/agent_manager.html`

**导航菜单示例**：

```
┌─────────────────────────────────────────────────────────────┐
│  Quest3 Agent                    [主页] [文档]        │
├─────────────────────────────────────────────────────────────┤
│                                                      │
│  快速入口                                             │
│  ─────────────────────────────────────────────────────   │
│  📝 智能聊天     → /static/index.html              │
│  🤖 Agent管理    → /static/agent_manager.html        │
│  🔗 MCP服务器    → /static/mcp_manager.html          │
│  📊 系统监控     → /static/dashboard.html             │
│                                                      │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 聊天界面增强

**Plan模式展示**：
```
📋 执行计划
├─ 复杂度: MEDIUM
├─ 策略: chain
└─ 步骤数: 3

步骤 1/3: read_file
├─ 状态: ✅ 完成
└─ 结果: [预览]

步骤 2/3: analyze_data
├─ 状态: ⏳ 执行中
...

最终回复: ...
```

**ReAct模式展示**：
```
思考 #1:
我需要先读取文件来了解数据...

行动 #1:
工具: read_file
参数: {"file_path": "data.txt"}

观察 #1:
读取成功，文件包含100行数据...

思考 #2:
现在我需要分析这些数据...
...
```

## 6. 实施步骤

### 阶段一：Agent管理系统（优先级：高）
1. ✅ 创建Agent数据模型
2. ✅ 创建数据库表
3. ✅ 实现AgentService
4. ✅ 创建Agent管理API
5. ⏳ 实现前端Agent管理界面

### 阶段二：ReAct模式执行器（优先级：高）
1. ⏳ 实现ReActExecutor类
2. ⏳ 实现ReAct提示词模板
3. ⏳ 实现行动解析器
4. ⏳ 集成工具过滤机制
5. ⏳ 单元测试

### 阶段三：执行策略路由（优先级：中）
1. ⏳ 实现ExecutionStrategyRouter
2. ⏳ 更新ChatService集成路由
3. ⏳ 支持Agent级别的配置传递

### 阶段四：前端展示优化（优先级：中）
1. ⏳ 实现Plan模式UI组件
2. ⏳ 实现ReAct模式UI组件
3. ⏳ 添加执行模式切换
4. ⏳ 优化消息流展示

### 阶段五：增强功能（优先级：低）
1. ⏳ Agent智能选择（基于任务类型）
2. ⏳ 执行历史记录
3. ⏳ 性能监控和统计
4. ⏳ Agent模板和克隆

## 7. 技术细节

### 7.1 工具权限控制

**三级权限**：
- **required**: 智能体必须使用该工具
- **optional**: 智能体可以使用该工具（默认）
- **forbidden**: 智能体不能使用该工具

**实现**：
```python
def filter_tools(agent: Agent, all_tools: Dict) -> Dict:
    """根据Agent配置过滤工具"""
    filtered = {}

    for tool_name, tool in all_tools.items():
        # 查找工具配置
        tool_config = next(
            (t for t in agent.tools if t.tool_name == tool_name),
            None
        )

        if tool_config:
            if tool_config.permission == "forbidden":
                continue
            filtered[tool_name] = tool
        else:
            # 未配置默认为optional
            filtered[tool_name] = tool

    return filtered
```

### 7.2 ReAct循环终止条件

**多种终止策略**：
1. LLM明确表示任务完成
2. 达到最大循环次数（防止无限循环）
3. 检测到重复行动（防止卡顿）
4. 工具执行连续失败超过阈值

**实现**：
```python
def should_terminate(
    execution_history: List,
    current_step: int,
    max_steps: int
) -> Tuple[bool, str]:
    """判断是否应该终止循环

    Returns:
        (should_terminate, reason)
    """
    if current_step >= max_steps:
        return True, "达到最大循环次数"

    # 检查重复行动
    if len(execution_history) > 1:
        last_action = execution_history[-1]["action"]
        prev_action = execution_history[-2]["action"]
        if last_action == prev_action:
            return True, "检测到重复行动"

    return False, ""
```

### 7.3 系统提示词增强

**ReAct模式提示词结构**：
```
# 角色定义
{agent.system_prompt}

# 任务描述
当前任务: {task}

# 工具列表
可用工具:
{filtered_tools_description}

# 执行要求
1. 仔细分析任务，按"思考→行动→观察"的格式回复
2. 每次只能执行一个工具调用
3. 观察工具执行结果后，决定下一步行动
4. 当任务完成时，使用"完成: [回复]"格式

# 执行历史
{execution_history_formatted}

# 当前轮次
当前轮次: {current_step}/{max_steps}

请开始执行:
```

## 8. 测试策略

### 8.1 单元测试
- AgentService CRUD操作
- ReActExecutor循环逻辑
- 工具过滤机制
- 行动解析器

### 8.2 集成测试
- 完整ReAct流程（工具调用→观察→继续）
- Agent切换和配置加载
- Plan/ReAct模式切换

### 8.3 端到端测试
- 前端→API→服务→LLM完整流程
- 多轮对话状态维护
- 错误处理和恢复

## 9. 风险和缓解

### 风险1: ReAct模式循环次数过多
- **缓解**: 设置合理最大步数（如10-15步）
- **缓解**: 实现提前终止检测

### 风险2: LLM格式解析失败
- **缓解**: 多种格式尝试（结构化/自然语言）
- **缓解**: 提供清晰的格式示例

### 风险3: 工具执行成本过高
- **缓解**: 执行前展示计划（Plan模式）
- **缓解**: 提供取消执行功能

## 10. 性能优化

### 10.1 并行优化
- Plan模式：执行可并行步骤时使用asyncio.gather()
- 多Agent场景：独立的执行上下文

### 10.2 缓存策略
- Agent配置缓存
- 工具描述缓存
- LLM响应缓存（对于相同输入）

### 10.3 资源管理
- 及时关闭未使用的连接
- 限制并发LLM调用数量
- 实现请求队列和速率限制

## 11. 扩展性考虑

### 11.1 未来执行模式
- **混合模式**: Plan + ReAct结合
- **协作模式**: 多Agent协同
- **人类在环**: 关键决策需人工确认

### 11.2 插件化架构
- 执行器插件系统
- 工具中间件
- 观察者模式事件系统

## 12. 总结

本方案通过引入ReAct模式和智能体管理系统，显著提升了Quest3 Agent的：

1. **灵活性**: 多种执行模式适应不同任务类型
2. **可配置性**: 精细化的Agent配置满足不同需求
3. **可观测性**: 详细的执行过程展示
4. **可扩展性**: 模块化架构支持未来扩展

实施建议按阶段逐步推进，优先完成Agent管理和ReAct执行器，然后逐步完善前端和增强功能。
