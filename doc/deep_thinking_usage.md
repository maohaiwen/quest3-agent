# 深度思考功能使用说明

## 概述

深度思考功能允许模型在回答用户问题之前展示其思考过程。支持多种推理深度级别，提供更透明的 AI 决策过程。

## 功能特性

- ✅ 支持所有执行模式（Direct、Plan、ReAct）
- ✅ 流式输出思考过程和回答
- ✅ 多级推理深度（minimal/low/medium/high）
- ✅ 兼容火山引擎 SDK 和 Anthropic API
- ✅ 保持前端事件格式兼容

## 配置

### 1. 安装依赖

```bash
pip install volcengine-python-sdk[ark]
```

或使用 uv：
```bash
uv pip install volcengine-python-sdk[ark]
```

### 2. 环境变量配置

在 `.env` 文件中添加：

```bash
# 火山引擎 API 配置
VOLCENGINE_API_KEY=your_api_key_here
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
VOLCENGINE_MODEL=doubao-seed-2.0-lite-260215
VOLCENGINE_DEFAULT_REASONING_EFFORT=medium
```

### 3. 推理深度级别

- `minimal`: 最小推理深度，快速响应，适合简单任务
- `low`: 低推理深度，平衡速度与质量
- `medium`: 中等推理深度，适合复杂问题（默认）
- `high`: 高推理深度，深度思考，适合复杂规划任务

## 使用方式

### WebSocket API

前端通过 WebSocket 发送消息时，可以开启深度思考：

```javascript
// 初始化连接
const ws = new WebSocket("ws://localhost:8000/api/chat/stream");

// 发送初始化消息
ws.send(JSON.stringify({
    session_id: "your_session_id",
    agent_id: "your_agent_id",  // 可选
    deep_thinking: true  // 开启深度思考
}));

// 或者在后续消息中开启/关闭
ws.send(JSON.stringify({
    message: "你的问题",
    deep_thinking: true
}));
```

### 事件格式

开启深度思考后，WebSocket 会返回以下事件：

```javascript
// 1. 思考开始
{
    "type": "thinking_start",
    "message": "开始思考..."
}

// 2. 思考内容（流式）
{
    "type": "thinking",
    "content": "这是模型的第一步思考..."
}

// 3. 思考内容（流式，继续）
{
    "type": "thinking",
    "content": "这是模型的第二步思考..."
}

// 4. 思考结束
{
    "type": "thinking_end",
    "message": "思考完成"
}

// 5. 回答内容（流式）
{
    "type": "message",
    "content": "这是模型的回答..."
}

// 6. 执行结束
{
    "type": "end"
}
```

### Agent 配置

可以在 Agent 配置中指定推理深度：

```json
{
    "name": "深度思考助手",
    "execution_mode": "direct",
    "model": "doubao-seed-2.0-lite-260215",
    "reasoning_effort": "high",
    "system_prompt": "你是一个专业的助手..."
}
```

## 代码示例

### Python 后端

```python
from app.core.strategy_router import strategy_router
from app.services.llm_service import llm_service

# 初始化
strategy_router.set_llm_client(llm_service.client)

# 执行任务（开启深度思考）
async for event in strategy_router.execute(
    task="解释量子计算的原理",
    deep_thinking=True
):
    event_type = event.get("type")

    if event_type == "thinking_start":
        print("开始思考...")
    elif event_type == "thinking":
        print(event.get("content"), end="", flush=True)
    elif event_type == "thinking_end":
        print("\n思考完成")
    elif event_type == "message":
        print(event.get("content"), end="", flush=True)
    elif event_type == "end":
        print("\n执行完成")
```

## 测试

运行测试脚本：

```bash
python test_deep_thinking.py
```

测试脚本会：
1. 测试 Direct 模式 + 深度思考
2. 测试 Plan 模式 + 深度思考
3. 对比深度思考模式 vs 普通模式

## 注意事项

1. **API 配置**: 确保已配置 `VOLCENGINE_API_KEY`，否则会回退到 Anthropic 客户端

2. **性能考虑**: 较高的推理深度（high）会增加响应时间和 token 消耗

3. **前端兼容性**: 确保前端能正确处理 `thinking` 和 `message` 事件流

4. **多轮对话**: 深度思考模式下，思考内容不会保存到对话历史中，只有回答内容会保存

5. **模型支持**: 不是所有模型都支持深度思考功能，使用支持 thinking 的模型

## 技术架构

```
前端 WebSocket
    ↓
chat.py (API 层)
    ↓
strategy_router (执行路由)
    ↓
llm_service (LLM 服务)
    ↓
Volcengine SDK / Anthropic API
```

关键组件：
- `ThinkingChainManager`: 思维链管理器
- `ConversationContext`: 对话上下文管理器
`ReasoningEffortStrategy`: 推理深度策略管理器
- `LLMService`: 统一的 LLM 服务接口

## 故障排查

### Volcengine SDK 未加载

```
[WARN] Volcengine SDK 未加载，将使用 Anthropic 客户端
```

**解决方案**: 安装 volcengine-python-sdk[ark]

### 没有看到思考过程

1. 检查 `deep_thinking` 参数是否设置为 `true`
2. 检查 `VOLCENGINE_API_KEY` 是否配置
3. 检查模型是否支持 thinking 功能

### 思考过程没有流式输出

确保前端正确处理流式事件：
- 使用 `thinking` 事件来更新思考内容
- 不要等待完整响应后再显示

## 相关文档

- [深度思考重构设计文档](deep_thinking_redesign.md)
- [火山引擎 SDK 文档](https://www.volcengine.com/docs/ark/README)
