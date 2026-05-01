# Quest3 Agent 智能体应用深度学习指南

## 目录

1. [项目概述](#项目概述)
2. [技术栈详解](#技术栈详解)
3. [核心概念深入](#核心概念深入)
4. [架构设计](#架构设计)
5. [模块详解](#模块详解)
6. [关键技术点](#关键技术点)
7. [设计模式应用](#设计模式应用)
8. [异步编程深入](#异步编程深入)
9. [部署与优化](#部署与优化)

---

## 项目概述

### 什么是智能体应用？

智能体（Agent）是一种能够感知环境、做出决策并执行行动的软件实体。在AI领域，大语言模型（LLM）智能体通常具备以下特征：

- **感知能力**: 通过对话接口接收用户输入
- **记忆能力**: 短期工作记忆和长期知识存储
- **推理能力**: 基于LLM进行上下文理解和生成
- **行动能力**: 调用工具、检索信息、执行操作

### 本项目的定位

Quest3 Agent是一个**对话式智能体**，专注于：
- 自然语言对话交互
- 多轮对话上下文管理
- 长短期记忆系统
- 实时流式响应

### 项目特色

1. **全异步架构**: 使用async/await实现高并发
2. **分层设计**: 清晰的关注点分离
3. **类型安全**: Pydantic提供运行时类型验证
4. **易于扩展**: 模块化设计便于功能扩展
5. **生产就绪**: 完善的错误处理和日志

---

## 技术栈详解

### 1. FastAPI：现代异步Web框架

#### 为什么选择FastAPI？

```python
# FastAPI vs Flask vs Django
# Flask: 同步框架，需要额外配置支持异步
# Django: 重量级框架，学习曲线陡峭
# FastAPI: 原生异步、自动文档、类型提示
```

**核心特性**：
- **异步支持**: 基于Starlette，原生async/await
- **自动文档**: OpenAPI/Swagger自动生成
- **类型验证**: Pydantic数据模型验证
- **依赖注入**: 优雅的依赖管理
- **性能优异**: 接近Node.js和Go

#### FastAPI应用生命周期

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    await db.initialize_schema()
    yield
    # 关闭时执行
    await db.disconnect()
```

`lifespan`机制确保资源正确初始化和清理，避免资源泄漏。

#### 依赖注入系统

```python
# 简单依赖
def get_db():
    return database

@router.get("/users")
async def get_users(db = Depends(get_db)):
    return db.query(User).all()

# 嵌套依赖
def get_current_user(db = Depends(get_db), token: str = Depends(get_token)):
    return verify_token(token, db)
```

依赖注入的**优势**：
- 测试友好：可以注入mock对象
- 代码复用：共享初始化逻辑
- 生命周期管理：自动处理资源
- 类型安全：编辑器支持自动补全

### 2. Pydantic：数据验证和设置管理

#### 数据模型定义

```python
from pydantic import BaseModel, Field, validator

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    message: str = Field(..., min_length=1, description="用户消息")

    @validator('message')
    def validate_message(cls, v):
        if v.strip() == '':
            raise ValueError('消息不能为空')
        return v
```

**Pydantic提供**：
- 类型自动转换和验证
- 详细错误信息
- JSON序列化/反序列化
- 数据模型文档生成

#### 配置管理

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True
    )

    ANTHROPIC_API_KEY: str = Field(default="")

settings = Settings()
```

Pydantic Settings自动从环境变量读取配置，支持：
- 环境变量覆盖
- 类型转换
- 默认值
- 配置验证

### 3. aiosqlite：异步SQLite

#### 为什么需要异步数据库？

```python
# 同步数据库的问题
def get_user(user_id):
    user = db.query(User).get(user_id)  # 阻塞事件循环
    return user

# 异步数据库的优势
async def get_user(user_id):
    user = await db.query(User).get(user_id)  # 非阻塞
    return user
```

在并发场景下：
- **同步IO**: 每个请求阻塞线程，需要大量线程
- **异步IO**: 单线程处理多个请求，资源利用率高

#### 连接池管理

```python
class DatabaseConnection:
    def __init__(self, database_url: str):
        self.connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        if self.connection is None:
            self.connection = await aiosqlite.connect(self.db_path)
            await self.connection.execute("PRAGMA journal_mode = WAL")
        return self.connection
```

**关键配置**：
- `journal_mode=WAL`: 写前日志模式，支持读写并发
- 单例模式：避免重复创建连接
- 延迟初始化：连接时才创建

### 4. Anthropic SDK：LLM API客户端

#### 同步 vs 异步调用

```python
# 同步调用（阻塞）
def chat_sync(message):
    client = Anthropic(api_key=key)
API_KEY)
    response = client.messages.create(...)
    return response

# 异步调用（非阻塞）
async def chat_async(message):
    client = AsyncAnthropic(api_key=key)
API_KEY)
    response = await client.messages.create(...)
    return response
```

异步调用在FastAPI中至关重要，避免阻塞事件循环。

#### 流式响应

```python
async def chat_stream(message):
    async with client.messages.stream(...) as stream:
        async for text in stream.text_stream:
            yield text
```

**流式响应的优势**：
- 用户体验：实时显示生成内容
- 资源效率：不需要等待完整响应
- 中断能力：用户可以随时停止生成

### 5. ChromaDB：向量数据库

#### 向量数据库原理

```
传统数据库：精确匹配
用户输入："苹果"
数据库查询：SELECT * FROM products WHERE name = "苹果"
结果：完全匹配"苹果"的产品

向量数据库：语义相似度
用户输入："苹果"
向量查询：query("苹果", top_k=5)
结果：["苹果手机", "苹果公司", "水果-苹果", ...]
```

#### ChromaDB使用

```python
class VectorService:
    def __init__(self):
        self.client = chromadb.PersistentClient(path="./chroma_db")

    def add(self, content: str, metadata: dict):
        collection = self.client.get_or_create_collection("session_123")
        collection.add(documents=[content], ids=[uuid()])

    def search(self, query: str):
        results = collection.query(query_texts=[query], n_results=5)
        return results
```

**ChromaDB特性**：
- 持久化存储：数据保存到本地
- 集合隔离：每个会话独立存储
- 元数据支持：存储额外信息
- 自动向量：内置embedding功能

---

## 核心概念深入

### 1. 智能体的记忆系统

#### 记忆层次结构

```
┌─────────────────────────────────────────┐
│         智能体记忆系统                │
├─────────────────────────────────────────┤
│  工作记忆 (Working Memory)            │
│  - 当前对话上下文                     │
│  - 最近的消息                         │
│  - 存储在内存中                      │
├─────────────────────────────────────────┤
│  短期记忆 (Short-term Memory)         │
│  - 当前会话的所有消息                  │
│  - 支持多轮对话                       │
│  - 存储在内存 + SQLite                │
├─────────────────────────────────────────┤
│  长期记忆 (Long-term Memory)          │
│  - 跨会话的知识                       │
│  - 语义搜索支持                       │
│  - 存储在向量数据库                   │
└─────────────────────────────────────────┘
```

#### 记忆管理策略

```python
class MemoryService:
    def __init__(self):
        self._sessions = {}  # 会话缓存

    def add_message(self, session_id, role, content):
        memory = self.get_or_create_session_memory(session_id)
        memory.add_message(role, content)

    def get_conversation_history(self, session_id, limit=None):
        memory = self.get_or_create_session_memory(session_id)
        return memory.get_last_n_messages(limit) if limit else memory.get_messages()
```

**设计考虑**：
- **会话隔离**: 每个会话独立记忆
- **内存限制**: 避免无限增长
- **快速访问**: 内存缓存提高性能
- **持久化**: 定期保存到数据库

### 2. 会话管理

#### 会话生命周期

```
创建 → 激活 → 交互 → 存档 → 归档/删除
  ↓       ↓       ↓        ↓          ↓
UUID   status  messages  timestamp   cleanup
```

#### 会话状态管理

```python
class SessionStatus(str, Enum):
    ACTIVE = "active"      # 活跃状态，可以进行对话
    INACTIVE = "inactive"  # 暂停状态，但不删除数据
    ARCHIVED = "archived"  # 归档状态，只读访问
```

状态机的**好处**：
- 明确的状态转换
- 防止非法操作
- 便于状态追踪
- 支持会话恢复

### 3. WebSocket实时通信

#### WebSocket vs HTTP

| 特性 | HTTP | WebSocket |
|------|------|-----------|
| 连接方式 | 请求-响应 | 持久连接 |
| 通信方向 | 客户端发起 | 双向 |
| 实时性 | 轮询或长轮询 | 实时推送 |
| 开销 | 每次请求携带头部 | 连接后低开销 |
| 使用场景 | RESTful API | 实时通信 |

#### WebSocket通信流程

```python
@router.websocket("/stream")
async def chat_stream(websocket: WebSocket):
    # 1. 建立连接
    await websocket.accept()

    try:
        # 2. 等待客户端消息
        data = await websocket.receive_json()
        session_id = data.get("session_id")

        # 3. 发送响应
        await websocket.send_json({"type": "connected"})

        # 4. 保持连接，处理后续消息
        while True:
            data = await websocket.receive_json()
            # 处理消息...

    except WebSocketDisconnect:
        # 5. 连接关闭处理
        pass
```

**关键点**：
- `accept()` 必须首先调用
- 使用try/except处理断开
- 保持长连接处理多轮交互
- 正确清理资源

---

## 架构设计

### 分层架构模式

```
┌─────────────────────────────────────┐
│     表现层 (Presentation Layer)     │
│  - FastAPI路由                     │
│  - WebSocket处理                   │
│  - 数据验证                        │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│   业务逻辑层 (Business Logic)       │
│  - 智能体核心逻辑                  │
│  - 对话状态管理                    │
│  - 记忆协调                        │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│      服务层 (Service Layer)          │
│  - LLM封装                         │
│  - 记忆服务                        │
│  - 向量存储                        │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│   数据访问层 (Data Access Layer)    │
│  - 数据库操作                      │
│  - 缓存管理                        │
│  - 数据持久化                      │
└─────────────────────────────────────┘
```

**分层的好处**：
1. **关注点分离**: 每层专注特定职责
2. **易于测试**: 可以mock依赖层
3. **灵活替换**: 更换实现不影响上层
4. **代码复用**: 服务层可被多个接口调用

### 依赖关系图

```
API Layer (chat.py, sessions.py, memory.py)
    ↓ 依赖
Core Layer (agent.py, conversation_handler.py)
    ↓ 依赖
Service Layer (llm_service.py, memory_service.py, vector_service.py)
    ↓ 依赖
Data Layer (connection.py, repositories.py)
    ↓ 依赖
Models & Config (chat.py, session.py, config.py)
```

---

## 模块详解

### 1. 配置模块 (app/config.py)

#### 环境变量管理

```python
class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = Field(default="")

    model_config = SettingsConfigDict(
        env_file=".env",        # 从.env文件读取
        env_file_encoding="utf-8",
        case_sensitive=True,      # 区分大小写
    )
```

**环境变量优先级**：
1. 系统环境变量（最高）
2. .env文件
3. 默认值（最低）

#### 配置验证

```python
class Settings(BaseSettings):
    PORT: int = Field(default=8000, ge=1, le=65535)

    @field_validator('PORT')
    def validate_port(cls, v):
        if v < 1024 and not is_root():
            raise ValueError('需要root权限绑定1024以下端口')
        return v
```

### 2. 数据模型 (app/models/)

#### Pydantic模型设计

```python
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum

class MessageRole(str, Enum):
    """消息角色枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class ChatRequest(BaseModel):
    """聊天请求模型"""
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=10000)

    @validator('session_id')
    def validate_session_id(cls, v):
        # UUID格式验证
        import uuid
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError('无效的会话ID格式')
        return v
```

**模型设计原则**：
- **字段验证**: 使用Field定义约束
- **类型安全**: 明确的类型注解
- **枚举类型**: 限制可选值
- **文档化**: description字段说明

### 3. 数据库模块 (app/database/)

#### 连接管理器

```python
class DatabaseConnection:
    def __init__(self, database_url: str):
        self.connection = None
        self.db_path = self._parse_url(database_url)

    async def connect(self):
        if self.connection is None:
            self.connection = await aiosqlite.connect(self.db_path)

            # 性能优化配置
            await self.connection.execute("PRAGMA foreign_keys = ON")   # 外键约束
            await self.connection.execute("PRAGMA journal_mode = WAL")     # 并发优化
            await self.connection.execute("PRAGMA synchronous = NORMAL")    # 性能优化

        return self.connection
```

**SQLite配置说明**：
- `foreign_keys=ON`: 启用外键约束
- `journal_mode=WAL`: 写前日志，读写并发
- `synchronous=NORMAL`: 平衡性能和安全

#### Repository模式

```python
class SessionRepository:
    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(self, session_data: SessionCreate) -> SessionCreateResponse:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        sql = "INSERT INTO sessions (...) VALUES (?,?,?)"
        await self.db.execute(sql, (session_id, ...))
        await self.db.commit()

        return SessionCreateResponse(session_id=session_id)

    async def get(self, session_id: str) -> Optional[SessionResponse]:
        sql = "SELECT * FROM sessions WHERE id = ?"
        row = await self.db.fetch_one(sql, (session_id,))
        return SessionResponse(**row) if row else None
```

**Repository模式优势**：
- 数据访问逻辑集中
- 易于切换数据库
- 统一错误处理
- 可添加缓存层

### 4. 服务模块 (app/services/)

#### LLM服务

```python
class LLMService:
    def __init__(self, api_key: str):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = "claude-3-5-sonnet-20241022"

    async def chat(self, message: str, history: list[) -> str:
        messages = self._build_messages(message, history)

        response = await self.client.messages.create(
            model=self.model,
            messages=messages,
            max_tokens=2000,
            temperature=0.7
        )

        return response.content[0].text

    def _build_messages(self, message, history):
        """构建LLM API消息格式"""
        messages = []

        # 添加历史消息
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        # 添加当前消息
        messages.append({"role": "user", "content": message})

        return messages
```

**LLM调用优化**：
- 消息格式标准化
- 历史消息管理
- 参数可配置
- 错误处理和重试

#### 记忆服务

```python
class ConversationMemory:
    def __init__(self, max_tokens: int = 1000):
        self._messages: List[dict] = []
        self.max_tokens = max_tokens

    def add_message(self, role: MessageRole, content: str):
        self._messages.append({
            "role": role.value,
            "content": content
        })

        # 令牌限制处理
        self._trim_to_token_limit()

    def get_messages(self) -> List[dict]:
        return self._messages.copy()
```

**记忆管理策略**：
- 滚动窗口：保留最近N条消息
- 令牌限制：总token数不超过阈值
- 时间衰减：旧消息权重降低

### 5. API模块 (app/api/)

#### RESTful API设计

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """处理聊天请求"""
    # 1. 验证会话
    session = await session_repo.get(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2. 保存用户消息
    await message_repo.create(...)

    # 3. 调用LLM
获取对话历史
    response = await llm_service.chat(...)

    # 4. 保存助手消息
    await message_repo.create(...)

    return ChatResponse(...)
```

**RESTful设计原则**：
- 使用HTTP方法（GET, POST, PUT, DELETE）
- 资源导向的URL设计
- 统一的响应格式
- 适当的HTTP状态码

#### WebSocket处理

```python
@router.websocket("/stream")
async def chat_stream(websocket: WebSocket):
    await websocket.accept()

    session_id = None
    try:
        # 初始化连接
        data = await websocket.receive_json()
        session_id = data.get("session_id")

        # 消息循环
        while True:
            data = await websocket.receive_json()
            message = data.get("message")

            # 流式生成响应
            async for chunk in llm_service.chat_stream(...):
                await websocket.send_json({"type": "message", "content": chunk})

            await websocket.send_json({"type": "end"})

    except WebSocketDisconnect:
        logger.info(f"Client {session_id} disconnected")
    except Exception as e:
        logger.error(f"Error: {e}")
```

---

## 关键技术点

### 1. 异步编程深入

#### async/await基础

```python
# 同步函数
def sync_function():
    result = time_consuming_operation()  # 阻塞
    return result

# 异步函数
async def async_function():
    result = await time_consuming_operation()  # 非阻塞
    return result
```

**异步原理**：
- `async`定义协程函数
- `await`挂起执行，等待结果
- 事件循环调度协程
- 单线程实现并发

#### 并发执行

```python
# 顺序执行（慢）
async def sequential():
    a = await fetch_data(1)
    b = await fetch_data(2)
    return a, b

# 并发执行（快）
async def concurrent():
    results = await asyncio.gather(
        fetch_data(1),
        fetch_data(2)
    )
    return results
```

**并发模式**：
- `asyncio.gather`: 等待所有任务完成
- `asyncio.wait`: 等待任意任务完成
- `asyncio.as_completed`: 按完成顺序获取结果

#### 异步上下文管理器

```python
@asynccontextmanager
async def database_session():
    conn = await get_connection()
    try:
        yield conn
    finally:
        await conn.close()

# 使用
async with database_session() as conn:
    result = await conn.execute(sql)
```

### 2. 类型注解与类型检查

#### Python类型系统

```python
from typing import Optional, List, Dict, Any, Union

# 基本类型
name: str = "John"
age: int = 25
is_active: bool = True

# 容器类型
items: List[str] = ["a", "b", "c"]
mapping: Dict[str, int] = {"key": 1.0}

# 可选类型
email: Optional[str] = None

# 联合类型
value: Union[str, int] = "hello"
```

#### 类型注解的好处

```python
def process_data(data: List[Dict[str, Any]]) -> Dict[str, int]:
    """处理数据并返回统计结果"""
    result = {}
    for item in data:
        result[item["name"]] = item["value"]
    return result

# 编辑器自动补全
# 类型检查工具可以捕获错误
# 代码自动文档化
```

### 3. 错误处理和日志

#### 结构化错误处理

```python
try:
    result = await risky_operation()
except ValueError as e:
    # 数据验证错误
    logger.warning(f"Invalid data: {e}")
    raise HTTPException(status_code=400, detail=str(e))
except ConnectionError as e:
    # 连接错误
    logger.error(f"Connection failed: {e}")
    raise HTTPException(status_code=503, detail="Service unavailable")
except Exception as e:
    # 未知错误
    logger.critical(f"Unexpected error: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Internal server error")
```

#### 日志最佳实践

```python
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 不同级别的日志
logger.debug("详细调试信息")    # 开发环境
logger.info("一般信息")          # 重要事件
logger.warning("警告信息")        # 潜在问题
logger.error("错误信息")          # 错误发生
logger.critical("严重错误")       # 系统崩溃
```

### 4. 数据库优化

#### 索引优化

```sql
-- 为常用查询字段创建索引
CREATE INDEX idx_messages_session_id ON messages(session_id);
CREATE INDEX idx_memory_session_id ON memory(session_id);

-- 复合索引
CREATE INDEX idx_messages_session_created
ON messages(session_id, created_at);
```

**索引使用原则**：
- 为WHERE条件字段创建索引
- 为JOIN字段创建索引
- 避免过多索引影响写入性能
- 定期分析索引使用情况

#### 查询优化

```python
# 低效查询：获取所有数据后过滤
async def get_messages_slow(session_id: str):
    all_messages = await db.fetch_all("SELECT * FROM messages")
    return [m for m in all_messages if m["session_id"] == session_id]

# 高效查询：使用WHERE条件
async def get_messages_fast(session_id: str):
    return await db.fetch_all(
        "SELECT * FROM messages WHERE session_id = ?",
        (session_id,)
    )
```

### 5. 缓存策略

#### 内存缓存

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_computation(x: int) -> int:
    """缓存计算结果"""
    print(f"Computing {x}")
    return x * x

# 第一次调用：计算
expensive_computation(5)  # 打印 "Computing 5"
# 第二次调用：从缓存获取
expensive_computation(5)  # 不打印
```

#### 缓存失效

```python
class CacheManager:
    def __init__(self, ttl: int = 300):
        self._cache = {}
        self._timestamps = {}
        self.ttl = ttl

    def get(self, key: str):
        if key in self._cache:
            if time.time() - self._timestamps[key] < self.ttl:
                return self._cache[key]
            else:
                self.invalidate(key)
        return None

    def set(self, key: str, value: any):
        self._cache[key] = value
        self._timestamps[key] = time.time()

    def invalidate(self, key: str):
        self._cache.pop(key, None)
        self._timestamps.pop(key, None)
```

---

## 设计模式应用

### 1. Repository模式

**目的**: 封装数据访问逻辑

```kt
class UserRepository(ABC):
    @abstractmethod
    async def get(self, user_id: str) -> Optional[User]:
        pass

    @abstractmethod
    async def save(self, user: User) -> None:
        pass

class SQLUserRepository(UserRepository):
    async def get(self, user_id: str) -> Optional[User]:
        # SQLite实现
        pass

class MockUserRepository(UserRepository):
    async def get(self, user_id: str) -> Optional[User]:
        # Mock实现用于测试
        pass
```

**优势**:
- 切换数据源不影响业务逻辑
- 便于单元测试
- 统一数据访问接口

### 2. 依赖注入

**目的**: 解耦组件依赖

```python
# 直接依赖（紧耦合）
class ChatHandler:
    def __init__(self):
        self.llm_service = LLMService()  # 硬编码依赖

# 依赖注入（松耦合）
class ChatHandler:
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service  # 依赖外部提供

# FastAPI自动注入
@router.post("/chat")
async def chat(
    request: ChatRequest,
    llm_service: LLMService = Depends(get_llm_service)
):
    handler = ChatHandler(llm_service)
    return await handler.handle(request)
```

### 3. 工厂模式

**目的**:根据配置创建对象

```python
class LLMFactory:
    @staticmethod
    def create(provider: str, **kwargs) -> LLMService:
        if provider == "anthropic":
            return AnthropicService(**kwargs)
        elif provider == "openai":
            return OpenAIService(**kwargs)
        else:
            raise ValueError(f"Unknown provider: {provider}")

# 使用
llm_service = LLMFactory.create(
    provider="anthropic",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)
```

### 4. 策略模式

**目的**: 可互换的算法

```python
class MemoryStrategy(ABC):
    @abstractmethod
    async def add(self, content: str) -> None:
        pass

    @abstractmethod
    async def search(self, query: str) -> List[str]:
        pass

class SimpleMemory(MemoryStrategy):
    async def add(self, content: str) -> None:
        # 简单实现
        pass

class VectorMemory(MemoryStrategy):
    async def add(self, content: str) -> None:
        # 向量搜索实现
        pass

class MemoryManager:
    def __init__(self, strategy: MemoryStrategy):
        self.strategy = strategy

    async def add(self, content: str):
        await self.strategy.add(content)
```

---

## 异步编程深入

### 事件循环机制

```python
import asyncio

async def task1():
    print("Task 1 started")
    await asyncio.sleep(1)
    print("Task 1 finished")

async def task2():
    print("Task 2 started")
    await asyncio.sleep(2)
    print("Task 2 finished")

async def main():
    # 创建任务
    t1 = asyncio.create_task(task1())
    t2 = asyncio.create_task(task2())

    # 等待完成
    await t1
    await t2

asyncio.run(main())
```

**事件循环工作原理**：
1. 主循环持续运行
2. 调度器管理协程
3. I/O事件触发协程恢复
4. 任务完成后从队列移除

### 异步生成器

```python
async def async_generator():
    for i in range(5):
        await asyncio.sleep(1)
        yield i

async def main():
    async for value in async_generator():
        print(f"Received: {value}")

asyncio.run(main())
```

**异步生成器应用**：
- 流式数据生成
- 服务器推送事件
- 实时数据处理

### 异步上下文

```python
class AsyncContext:
    def __init__(self, resource):
        self.resource = resource

    async def __aenter__(self):
        print("Acquiring resource")
        await asyncio.sleep(0.1)
        return self.resource

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("Releasing resource")
        await asyncio.sleep(0.1)

async def main():
    async with AsyncContext("database") as db:
        print(f"Using {db}")

asyncio.run(main())
```

---

## 部署与优化

### 性能优化

#### 1. 数据库连接池

```python
# 使用连接池
from aiomysql import create_pool

async def get_pool():
    pool = await create_pool(
        host='localhost',
        port=3306,
        user='root',
        password='password',
        db='test',
        minsize=5,      # 最小连接数
        maxsize=20,     # 最大连接数
    )
    return pool
```

#### 2. 响应压缩

```python
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,  # 小于1KB不压缩
    compresslevel=6       # 压缩级别
)
```

#### 3. 静态文件缓存

```python
from fastapi.staticfiles import StaticFiles

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)

# Nginx配置静态文件缓存
# location /static {
#     expires 7d;
#     add_header Cache-Control "public, immutable";
# }
```

### 部署方案

#### Docker部署

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ../docs .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port-workers", "4"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - ./data:/app/data
```

#### Nginx反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_passfolios http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    location /static {
        alias /app/static;
        expires 7d;
    }
}
```

### 监控和日志

#### 健康检查

```python
@app.get("/health")
async def health_check():
    checks = {
        "database": await check_database(),
        "llm": check_llm(),
        "vector_store": check_vector_store()
    }

    all_healthy = all(checks.values())

    return {
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks
    }
```

#### 结构化日志

```python
import json
import logging

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)
```

---

## 总结

### 核心学习要点

1. **异步编程**: async/await、事件循环、并发处理
2. **类型系统**: Pydantic验证、类型注解、类型安全
3. **数据库设计**: Repository模式、索引优化、异步操作
4. **API设计**: RESTful规范、WebSocket、依赖注入
5. **架构模式**: 分层设计、依赖解耦、可扩展性

### 实践建议

1. **从小开始**: 先实现核心功能，逐步完善
2. **测试驱动**: 编写测试确保功能正确
3. **文档先行**: 清晰的文档便于维护
4. **性能优先**: 关注性能瓶颈和优化机会
5. **安全考虑**: 输入验证、错误处理、日志记录

### 扩展方向

1. **用户认证**: JWT token、OAuth
2. **多用户支持**: 用户隔离、权限管理
3. **更多LLM提供商**: OpenAI、Google、本地模型
4. **工具调用**: Function Calling、插件系统
5. **前端优化**: React/Vue、状态管理
6. **部署优化**: Kubernetes、负载均衡、监控

---

**祝你学习愉快！如有疑问，欢迎讨论交流。**
