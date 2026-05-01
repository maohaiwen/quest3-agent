
# Quest3 Agent 架构设计文档

## 1. 概述

Quest3 Agent 是一个基于 FastAPI 和 Anthropic Claude API 的智能体聊天应用，支持多轮对话和长短期记忆管理。

## 2. 架构分层

### 2.1 表现层（Presentation Layer）

**文件**: `app/api/`

职责：
- 定义REST API接口和WebSocket端点
- 处理HTTP请求和响应
- 数据验证和转换

主要模块：
- `chat.py`: 聊天相关接口
  - `POST /api/chat/chat`: 发送聊天消息
  - `WS /api/chat/stream`: WebSocket流式聊天
- `sessions.py`: 会话管理接口
- `memory.py`: 记忆管理接口

### 2.2 业务逻辑层（Business Logic Layer）

**文件**: `app/core/`

职责：
- 实现核心业务逻辑
- 协调各服务之间的交互
- 处理业务规则和流程

### 2.3 服务层（Service Layer）

**文件**: `app/services/`

职责：
- 封装外部服务调用
- 提供业务功能服务

主要服务：
- `LLMService`: 与Anthropic Claude API交互
- `MemoryService`: 管理短期会话记忆
- `VectorService`: 管理长期向量记忆

### 2.4 数据访问层（Data Access Layer）

**文件**: `app/database/`

职责：
- 数据库连接管理
- 数据持久化操作

主要组件：
- `DatabaseConnection`: 异步SQLite连接管理
- `SessionRepository`: 会话数据访问
- `MessageRepository`: 消息数据访问
- `MemoryRepository`: 记忆数据访问

### 2.5 数据模型层（Model Layer）

**文件**: `app/models/`

职责：
- 定义数据结构
- 数据验证

### 2.6 配置层（Configuration Layer）

**文件**: `app/config.py`

职责：
- 管理应用配置
- 读取环境变量

## 3. 核心流程

### 3.1 聊天流程

```
用户消息 → API层 → 业务逻辑层 → 服务层调用
  ↓                              ↓
会话验证                          LLM服务调用
  ↓                              ↓
消息存储                        记忆检索
  ↓                              ↓
记忆更新                        返回响应
  ↓
返回结果
```

### 3.2 记忆管理流程

**短期记忆**：
- 存储在内存中的 `ConversationMemory`
- 保存当前会话的消息历史
- 用于多轮对话上下文

**长期记忆**：
- 存储在 ChromaDB 向量数据库
- 支持语义搜索
- 用于跨会话的知识检索

### 3.3 WebSocket流程

```
1. 客户端连接 → WebSocket握手
2. 发送session_id → 验证会话
3. 加载历史消息 → 初始化记忆
4. 发送用户消息 → 流式LLM响应
5. 接收流式响应 → 实时显示
6. 存储消息 → 更新记忆
```

## 4. 数据存储设计

### 4.1 SQLite数据库表

**sessions表**:
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    title TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

**messages表**:
```sql
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
)
```

**memory表**:
```sql
CREATE TABLE memory (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
)
```

### 4.2 向量存储

使用 ChromaDB 作为向量数据库：
- 每个会话一个独立的集合
- 支持语义搜索和相似度检索
- 持久化存储在本地文件系统

## 5. 依赖管理

### 5.1 核心依赖

- **FastAPI**: Web框架
- **Anthropic**: LLM API客户端
- **LangChain**: 智能体框架
- **ChromaDB**: 向量数据库
- **SQLAlchemy**: 数据库ORM
- **aiosqlite**: 异步SQLite驱动

### 5.2 依赖注入

使用 FastAPI 的依赖注入系统：
- 单例模式的服务实例
- 自动管理生命周期
- 便于测试和扩展

## 6. 安全考虑

### 6.1 API密钥管理

- 使用环境变量存储敏感信息
- 不将 `.env` 文件提交到版本控制
- 提供 `.env.example` 模板

### 6.2 数据验证

- 使用 Pydantic 进行数据验证
- 类型安全的输入输出

### 6.3 错误处理

- 完善的异常处理机制
- 详细的日志记录
- 用户友好的错误消息

## 7. 扩展性设计

### 7.1 LLM提供商切换

通过配置 `LLM_MODEL` 和相关服务，可以轻松切换不同的LLM提供商。

### 7.2 记忆存储扩展

向量存储服务可以替换为其他向量数据库实现（如 Milvus、Pinecone 等）。

### 7.3 插件系统

预留了工具调用和插件接口，便于扩展智能体能力。

## 8. 性能优化

### 8.1 异步处理

- 全异步架构，支持高并发
- 使用 aiosqlite 进行异步数据库操作

### 8.2 连接池

- 数据库连接复用
- 减少连接建立开销

### 8.3 流式响应

- WebSocket支持流式LLM响应
- 提升用户体验

## 9. 部署建议

### 9.1 开发环境

```bash
python main.py
```

### 9.2 生产环境

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 9.3 Docker部署

建议使用 Docker 容器化部署，配合 Nginx 作为反向代理。
