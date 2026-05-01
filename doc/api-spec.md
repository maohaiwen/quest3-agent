# Quest3 Agent API 接口规范

## 基础信息

- **Base URL**: `http://localhost:8000`
- **API版本**: v0.1.0
- **协议**: HTTP/1.1, WebSocket

## 通用响应格式

### 成功响应
```json
{
  "success": true,
  "data": {},
  "message": "操作成功"
}
```

### 错误响应
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述"
  }
}
```

## API 端点

### 1. 聊天接口

#### 1.1 发送聊天消息

**端点**: `POST /api/chat/chat`

**请求体**:
```json
{
  "session_id": "string (UUID)",
  "message": "string"
}
```

**响应**:
```json
{
  "response": "string (AI回复内容)",
  "timestamp": "string (ISO8601格式)",
  "message_id": "string (UUID)",
  "session_id": "string (UUID)"
}
```

**错误码**:
- `404`: 会话不存在
- `500`: LLM服务错误

#### 1.2 WebSocket流式聊天

**端点**: `WS /api/chat/stream`

**连接参数**: 通过查询参数传递 `session_id`

**消息格式**:

**客户端发送**:
```json
{
  "type": "message",
  "session_id": "string (UUID)",
  "message": "string"
}
```

**服务端响应**:
```json
{
  "type": "message|error|end|connected",
  "content": "string (消息内容)",
  "session_id": "string (UUID)"
}
```

**消息类型**:
- `connected`: 连接成功建立
- `message`: 流式消息内容
- `end`: 消息发送完成
- `error`: 错误信息

### 2. 会话管理接口

#### 2.1 创建会话

**端点**: `POST /api/sessions/create`

**请求体**:
```json
{
  "user_id": "string (可选)",
  "title": "string (可选)"
}
```

**响应**:
```json
{
  "session_id": "string (UUID)",
  "created_at": "string (ISO8601格式)"
}
```

#### 2.2 获取会话信息

**端点**: `GET /api/sessions/{session_id}`

**路径参数**:
- `session_id`: 会话ID

**响应**:
```json
{
  "id": "string (UUID)",
  "user_id": "string",
  "title": "string",
  "status": "active|inactive|archived",
  "created_at": "string (ISO8601格式)",
  "updated_at": "string (ISO8601格式)",
  "message_count": "integer"
}
```

**错误码**:
- `404`: 会话不存在

#### 2.3 获取会话历史

**端点**: `GET /api/sessions/{session_id}/history`

**路径参数**:
- `session_id`: 会话ID

**响应**:
```json
{
  "session_id": "string (UUID)",
  "messages": [
    {
      "id": "string (UUID)",
      "role": "user|assistant|system",
      "content": "string",
      "created_at": "string (ISO8601格式)"
    }
  ]
}
```

#### 2.4 更新会话

**端点**: `PUT /api/sessions/{session_id}`

**路径参数**:
- `session_id`: 会话ID

**请求体**:
```json
{
  "title": "string (可选)",
  "status": "active|inactive|archived (可选)"
}
```

**响应**: 返回更新后的会话信息

#### 2.5 删除会话

**端点**: `DELETE /api/sessions/{session_id}`

**路径参数**:
- `session_id`: 会话ID

**响应**:
```json
{
  "message": "Session deleted successfully"
}
```

### 3. 记忆管理接口

#### 3.1 存储记忆

**端点**: `POST /api/memory/store`

**请求体**:
```json
{
  "session_id": "string (UUID)",
  "content": "string",
  "metadata": {
    "key": "value"
  }
}
```

**响应**:
```json
{
  "memory_id": "string (UUID)",
  "created_at": "string (ISO8601格式)"
}
```

#### 3.2 搜索记忆

**端点**: `GET /api/memory/search`

**查询参数**:
- `query`: 搜索查询字符串
- `session_id`: 会话ID
- `limit`: 返回结果数量（默认5）

**响应**:
```json
{
  "results": [
    {
      "id": "string (UUID)",
      "session_id": "string (UUID)",
      "content": "string",
      "metadata": {},
      "created_at": "string (ISO8601格式)"
    }
  ],
  "query": "string",
  "count": "integer"
}
```

#### 3.3 删除记忆

**端点**: `DELETE /api/memory/{memory_id}`

**路径参数**:
- `memory_id`: 记忆ID

**响应**:
```json
{
  "message": "Memory deleted successfully"
}
```

## 4. 系统接口

### 4.1 健康检查

**端点**: `GET /health`

**响应**:
```json
{
  "status": "healthy",
  "llm_configured": "boolean",
  "vector_store_available": "boolean"
}
```

### 4.2 根路径

**端点**: `GET /`

**响应**:
```json
{
  "message": "Quest3 Agent API",
  "version": "0.1.0",
  "docs": "/docs",
  "chat_test": "/static/index.html"
}
```

## WebSocket 连接管理

### 连接流程

1. 客户端发起WebSocket连接
2. 连接建立后，客户端发送包含 `session_id` 的消息
3. 服务端验证会话并加载历史消息
4. 连接进入消息交换状态
5. 任何一方可以关闭连接

### 心跳机制

建议客户端实现心跳机制，定期发送ping消息保持连接活跃。

### 重连策略

连接断开后，客户端应实现指数退避的重连策略。

## 数据类型

### UUID格式
- 36字符的标准UUID格式
- 示例: `550e8400-e29b-41d4-a716-446655440000`

### 时间格式
- ISO8601格式
- 示例: `2026-04-17T10:30:00Z`

### 枚举类型

#### 消息角色 (MessageRole)
- `user`: 用户消息
- `assistant`: AI助手消息
- `system`: 系统消息

#### 会话状态 (SessionStatus)
- `active`: 活跃状态
- `inactive`: 非活跃状态
- `archived`: 已归档状态

## 错误码

| 错误码 | 描述 | HTTP状态码 |
|--------|------|------------|
| SESSION_NOT_FOUND | 会话不存在 | 404 |
| INVALID_SESSION_ID | 无效的会话ID | 400 |
| LLM_NOT_CONFIGURED | LLM服务未配置 | 500 |
| LLM_API_ERROR | LLM API调用失败 | 500 |
| VECTOR_STORE_ERROR | 向量存储错误 | 500 |
| DATABASE_ERROR | 数据库错误 | 500 |

## 速率限制

当前版本未实现速率限制，建议生产环境中添加：
- 每个会话每分钟消息数限制
- 每个用户的并发连接数限制
- API调用频率限制

## 版本管理

API版本通过URL路径或请求头指定（未来版本）。
当前所有接口为v0.1.0，可能随版本升级发生变化。

## 示例代码

### Python 示例

```python
import httpx
import json

async def chat_with_agent(session_id: str, message: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/chat/chat",
            json={
                "session_id": session_id,
                "message": message
            }
        )
        return response.json()

# 创建会话
async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/api/sessions/create"
    )
    session_data = response.json()
    session_id = session_data["session_id"]

# 聊天
result = await chat_with_agent(session_id, "你好，我是谁？")
print(result["response"])
```

### JavaScript 示例

```javascript
// WebSocket 连接
const ws = new WebSocket('ws://localhost:8000/api/chat/stream');

ws.onopen = function() {
    // 发送会话信息
    ws.send(JSON.stringify({
        type: 'connect',
        session_id: 'your-session-id'
    }));
};

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    if (data.type === 'message') {
        console.log('AI回复:', data.content);
    }
};

// 发送消息
function sendMessage(message) {
    ws.send(JSON.stringify({
        type: 'message',
        message: message
    }));
}
```
