# Agent 执行模式调用链路

## 概述

本文档描述 Quest3 Agent 中不同执行模式的完整调用链路，从用户消息发起到最终响应的全过程。

---

## 执行模式总览

系统支持以下 5 种执行模式：

| 模式 | 枚举值 | 说明 |
|------|--------|------|
| Direct Mode | `direct` | 直接 LLM 调用，带思维链显示 |
| Plan Mode | `plan` | 先规划后执行 |
| ReAct Mode | `react` | 思考→行动→观察循环 |
| ReAct Cot Mode | `react_cot` | 连贯思维链模式（推荐） |
| Thinking While Doing | `thinking_while_doing` | 边思考边执行（已废弃） |

---

## 1. Direct Mode (direct) - 直接模式

### 特点
- 最简单的执行模式
- 直接调用 LLM，带思维链显示
- 不调用工具

### 调用链路

```
用户消息
    ↓
Frontend (index.html)
    ↓
WebSocket API (chat.py → chat_stream())
    ↓
Strategy Router (strategy_router.py → execute())
    ↓
LLM Service (llm_service.py → _chat_completion_stream_with_thinking())
    ↓
Volcengine API / 其他 LLM API
    ↓
流式响应返回
    ↓
前端渲染
```

### 详细流程

1. **前端发起 WebSocket 连接**
   ```javascript
   // 在 connectWebSocket() 中
   ws.send({
       session_id: "...",
       agent_id: "...",
       deep_thinking: true/false
   })
   ```

2. **后端 WebSocket 接收事件** (chat.py)
   - 验证 session 和 agent
   - 检查 execution_mode == "direct"
   - 调用 `strategy_router.execute()`

3. **Strategy Router 执行** (strategy_router.py)
   - 构建 messages（对话历史 + 当前任务）
   - 调用 `llm_service._chat_completion_stream_with_thinking()`
   - 流式 yield 事件：
     - `thinking_start`
     - `thinking`
     - `thinking_end`
     - `message`
     - `end`

4. **LLM Service 处理** (llm_service.py)
   - 调用火山引擎 API（带 reasoning_content）
   - 流式返回思考和内容

---

## 2. Plan Mode (plan) - 规划模式

### 特点
- 先规划，后执行
- 先列出步骤，再依次执行
- 完整的任务分解

### 调用链路

```
用户消息
    ↓
Frontend (index.html)
    ↓
WebSocket API (chat.py → chat_stream())
    ↓
Planning Chat Service (planning_chat_service.py → chat())
    ↓
Phase 1: 规划阶段
    ↓
LLM Service → 获取规划
    ↓
Phase 2: 执行阶段
    ↓
ReAct Executor OR Direct Tool Call
    ↓
工具执行 (mcp_pool.py → call_tool())
    ↓
结果整合
    ↓
流式响应返回
```

### 详细流程

1. **WebSocket 接收事件** (chat.py)
   - 检查 execution_mode == "plan"
   - 调用 `planning_chat_service.chat()`

2. **规划阶段** (planning_chat_service.py)
   - 调用 LLM 生成执行计划
   - yield `planning` 事件（包含步骤列表）

3. **执行阶段**
   - 对每一个步骤：
     - yield `step_start`
     - 调用工具（如果需要）
     - yield `observation`
     - yield `step_complete`

4. **最终答案**
   - 整合所有执行结果
   - yield `complete`

---

## 3. ReAct Mode (react) - ReAct 循环模式

### 特点
- Thought → Action → Observation 循环
- 每一步独立思考
- 完整的执行历史

### 调用链路

```
用户消息
    ↓
WebSocket API (chat.py → chat_stream())
    ↓
Planning Chat Service (planning_chat_service.py → chat())
    ↓ [use_react = True]
    ↓
ReAct Executor (react_executor.py → execute())
    ↓
循环开始 (最多 max_steps 次)
    ↓
    ↓→ 思考阶段
    ↓   → LLM Service → _chat_completion_stream_with_thinking()
    ↓   → yield thinking_start, thinking, thinking_end
    ↓
    ↓→ 行动阶段
    ↓   → 解析工具调用
    ↓   → MCP Pool → call_tool()
    ↓   → yield action_start
    ↓
    ↓→ 观察阶段
    ↓   → yield observation
    ↓   → 记录到 execution_history
    ↓
    ↓→ 继续下一循环 ←┘
    ↓
任务完成 → yield complete
```

### 详细流程

1. **ReAct Executor 初始化** (react_executor.py)
   - 加载可用工具
   - 初始化执行历史

2. **主循环**
   ```python
   for step in range(max_steps):
       # 1. 思考
       thought = llm_think(context)
       
       # 2. 行动
       if tool_call:
           observation = execute_tool()
       
       # 3. 观察
       record_history()
       
       # 4. 检查是否完成
       if task_completed:
           break
   ```

3. **构建上下文** (`_build_context()`)
   - 当前任务
   - 可用工具
   - 完整执行历史（思考+行动+观察）
   - 对话历史

---

## 4. ReAct Cot Mode (react_cot) - 连贯思维链模式

### 特点
- ✨ 推荐使用
- 单个连贯的思维链容器
- 工具调用无缝嵌入思考
- 没有步骤分隔感，自然流畅

### 调用链路

```
用户消息
    ↓
WebSocket API (chat.py → chat_stream())
    ↓
ReAct Cot Executor (react_cot_executor.py → execute())
    ↓
创建思维链容器 (仅一次)
    ↓
循环开始 (最多 max_steps 次)
    ↓
    ↓→ 思考阶段
    ↓   → 构建包含历史的提示词
    ↓   → LLM Service → 流式思考
    ↓   → yield cot_thinking (追加到同一容器)
    ↓
    ↓→ 决策阶段
    ↓   → _parse_action_decision()
    ↓
    ↓→ 如果需要工具调用
    ↓   → yield cot_phase (tool-call)
    ↓   → yield cot_action (工具名+参数)
    ↓   → MCP Pool → call_tool()
    ↓   → yield cot_phase (observation)
    ↓   → yield cot_observation (结果)
    ↓
    ↓→ 如果任务完成
    ↓   → yield cot_phase (summarizing)
    ↓   → yield cot_phase (complete)
    ↓   → yield cot_complete (最终答案)
    ↓
    ↓→ 继续下一循环 ←┘
```

### 详细流程

1. **初始化** (react_cot_executor.py)
   - 加载可用工具
   - 初始化执行历史

2. **发送容器创建事件**
   ```python
   yield {"type": "cot_step_start", "step": 1}
   ```

3. **主循环**
   ```python
   for step in range(max_steps):
       # 1. 深度思考（流式）
       thinking_content = ""
       async for thinking in llm_think():
           thinking_content += thinking
           yield {"type": "cot_thinking", "content": thinking}
       
       # 2. 解析决策
       action = _parse_action_decision(thinking_content)
       
       # 3. 工具调用或完成
       if action.complete:
           yield final_answer
           break
       else:
           yield tool_call
           observation = execute_tool()
           yield observation
   ```

4. **思考连贯性优化**
   - 第 2 步开始，提示词强调"不要从头重复"
   - 提供完整的历史（思考+工具+观察）
   - 要求用"好的，从刚才的搜索结果中..."衔接

---

## 5. Thinking While Doing Mode (thinking_while_doing) - 已废弃

### 状态
❌ 已废弃，请不要使用

### 说明
此模式已从代码库中移除，保留枚举值仅用于向后兼容。

---

## 核心组件详解

### A. MCP Pool (mcp_pool.py)

工具调用的核心模块，管理所有 MCP 工具。

```python
# 获取所有可用工具
tools = await mcp_client_pool.get_all_tools()

# 调用工具
result = await mcp_client_pool.call_tool(tool_name, arguments)
```

### B. LLM Service (llm_service.py)

统一的 LLM 调用接口，支持思维链。

```python
# 核心方法
async def _chat_completion_stream_with_thinking(
    messages, model, temperature, max_tokens,
    system_prompt, enable_thinking, reasoning_effort
)
# Yields (content, thinking) tuples
```

### C. Strategy Router (strategy_router.py)

Direct 模式的执行器。

### D. Planning Chat Service (planning_chat_service.py)

Plan 模式和原 ReAct 模式的执行器。

---

## Agent 配置加载流程

```
Agent 配置 (agent_service.py)
    ↓
从数据库加载
    ↓
agent_config = {
    name: "...",
    execution_mode: "react_cot",
    model: "...",
    temperature: 0.7,
    max_tokens: 4096,
    system_prompt: "...",
    tools: ["web_search", "read_file"],
    thinking_effort: "medium",
    max_react_steps: 15
}
    ↓
传入对应的 Executor
    ↓
Executor 使用配置进行初始化
```

---

## 事件类型总结

### 通用事件

| 事件类型 | 说明 |
|---------|------|
| `connected` | WebSocket 连接建立 |
| `history` | 历史消息 |
| `message` | 普通消息内容 |
| `end` | 结束标志 |
| `error` | 错误 |

### 思维链相关事件

| 事件类型 | 说明 |
|---------|------|
| `thinking_start` | 开始思考 |
| `thinking` | 思考内容（流式） |
| `thinking_end` | 思考完成 |

### Plan 模式事件

| 事件类型 | 说明 |
|---------|------|
| `planning` | 规划内容 |
| `step_start` | 步骤开始 |
| `step_complete` | 步骤完成 |
| `step_error` | 步骤错误 |

### ReAct 模式事件

| 事件类型 | 说明 |
|---------|------|
| `phase` | 当前阶段 |
| `action_start` | 行动开始 |
| `observation` | 观察结果 |

### ReAct Cot 模式事件

| 事件类型 | 说明 |
|---------|------|
| `cot_step_start` | 思维链容器创建 |
| `cot_thinking` | 思考内容（流式追加） |
| `cot_phase` | 当前阶段（thinking/tool-call/observation） |
| `cot_action` | 工具调用 |
| `cot_observation` | 观察结果 |
| `cot_summarizing` | 总结中 |
| `cot_complete` | 最终答案 |

---

## 数据库 Schema 关系

```
Agent (agents table)
    ├─ id
    ├─ name
    ├─ execution_mode (plan/react/react_cot/direct)
    ├─ model
    ├─ temperature
    ├─ max_tokens
    ├─ system_prompt
    ├─ tools (JSON list)
    ├─ thinking_effort
    └─ max_react_steps

Session (sessions table)
    ├─ id
    ├─ title
    └─ agent_id (关联 Agent)

Message (messages table)
    ├─ id
    ├─ session_id (关联 Session)
    ├─ role (user/assistant)
    ├─ content
    └─ timestamp
```

---

## 推荐使用模式

| 场景 | 推荐模式 | 原因 |
|------|---------|------|
| 简单对话 | Direct | 快速，低延迟 |
| 复杂任务分解 | Plan | 清晰的步骤规划 |
| 需要工具调用 | ReAct | 可靠的循环执行 |
| 最佳体验 | **ReAct Cot** | 连贯的思维链，自然流畅 ✨ |
