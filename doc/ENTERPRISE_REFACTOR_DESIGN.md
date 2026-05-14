# Quest3 Agent 企业级改造设计文档

> 版本: v1.0 | 日期: 2026-05-14

---

## 一、改造目标

将 Quest3 Agent 从"能跑的原型"改造为"可部署生产的企业级应用"，核心指标：

- **安全性**：通过 OWASP Top 10 基本审查
- **可靠性**：单实例 99.9% 可用性，数据不丢失
- **可观测性**：故障 5 分钟内定位根因
- **可维护性**：新功能 1 人天可交付，CI 全自动
- **可扩展性**：支持水平扩展至多实例

---

## 二、改造清单（7 大领域，30 项）

### 领域 1：认证与安全 [P0 - 最高优先级]

#### 1.1 JWT 认证体系
**现状**：登录接口返回明文用户信息，无 token，前端靠 localStorage 存 username。
**目标**：JWT + Refresh Token 双 token 机制。

```
改造内容：
├── 引入 python-jose + passlib[bcrypt]
├── app/core/security.py（新增）
│   ├── create_access_token(identity, role, expires=30m)
│   ├── create_refresh_token(identity, expires=7d)
│   ├── verify_token(token) -> TokenPayload
│   └── hash_password(password) / verify_password(password, hash)
├── app/api/deps.py（新增）
│   └── get_current_user(token: str = Depends(oauth2_scheme)) -> User
├── app/api/users.py（改造）
│   ├── POST /login → 返回 {access_token, refresh_token, token_type}
│   └── 所有管理接口加 Depends(get_current_user)
└── 前端 static/（改造）
    ├── 登录后存储 token，请求头带 Authorization: Bearer xxx
    └── token 过期自动 refresh 或跳转登录
```

**关键改动文件**：`app/api/users.py`, `app/services/user_service.py`, 前端 `static/core/Auth.js`

#### 1.2 密码安全
**现状**：SHA-256 无盐哈希，4 位密码即可。
**目标**：bcrypt 加盐哈希，密码策略 ≥8 位。

```
改造内容：
├── user_service._hash_password → bcrypt.hash(password)
├── user_service.authenticate → bcrypt.verify(password, hash)
├── 密码策略：≥8 位，含大小写+数字
└── 旧密码迁移：首次登录时检测 sha256 格式，验证通过后自动升级为 bcrypt
```

**关键改动文件**：`app/services/user_service.py`

#### 1.3 WebSocket 认证
**现状**：WebSocket 无任何认证，任何人可连接。
**目标**：连接时验证 JWT。

```
改造内容：
├── app/api/chat.py → chat_stream 端点
│   ├── 连接时从 query params 或首条消息中提取 token
│   ├── 验证失败直接 close(code=4001)
│   └── 连接后定期检查 token 是否被撤销
```

**关键改动文件**：`app/api/chat.py:425-763`

#### 1.4 CORS + 安全头
**现状**：无 CORS 配置，无安全头。
**目标**：严格 CORS + 标准安全头。

```python
# app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),  # 从配置读取
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 安全头中间件：X-Content-Type-Options, X-Frame-Options, CSP
```

**关键改动文件**：`app/main.py`

#### 1.5 API 速率限制
**现状**：无限制。
**目标**：登录 5次/分钟，API 60次/分钟，WebSocket 消息 20次/分钟。

```
改造内容：
├── 引入 slowapi
├── app/core/rate_limit.py（新增）
│   └── limiter = Limiter(key_func=get_remote_address)
└── 关键端点加 @limiter.limit("5/minute")
```

#### 1.6 文件系统工具沙箱化
**现状**：`filesystem.py` 可读写服务器任意文件（base_path="."）。
**目标**：限定工作目录，禁止路径穿越。

```python
# app/tools/filesystem.py
ALLOWED_BASE = Path(settings.TOOL_SANDBOX_DIR).resolve()

def _resolve_safe_path(file_path: str) -> Path:
    """解析路径并确保不越界"""
    full = (ALLOWED_BASE / file_path).resolve()
    full.relative_to(ALLOWED_BASE)  # ValueError if escape
    return full
```

**关键改动文件**：`app/tools/filesystem.py`

---

### 领域 2：数据层 [P0]

#### 2.1 数据库连接池
**现状**：全局单一 aiosqlite 连接，无并发保护。
**目标**：连接池 + 复用。

```
改造内容：
├── 引入 aiosqlite 连接池（或切换到 SQLAlchemy async engine）
├── app/database/connection.py（改造）
│   ├── DatabaseConnection → 维护连接池 (min=2, max=10)
│   ├── acquire() / release() 上下文管理
│   └── 写操作加 asyncio.Lock 防止并发写冲突（SQLite WAL 模式限制）
└── 长远：评估迁移到 PostgreSQL（支持真正的并发）
```

**关键改动文件**：`app/database/connection.py`

#### 2.2 数据库迁移系统
**现状**：`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN` + `except: pass`。
**目标**：Alembic 版本化迁移。

```
改造内容：
├── 引入 alembic
├── alembic.ini + alembic/env.py（新增）
├── 将 connection.py 中的 schema 定义转为 SQLAlchemy Model
│   ├── app/models/db_models.py（新增）— ORM 模型定义
│   └── 所有表：sessions, messages, memory, skills, agents, ...
├── 初始化迁移：alembic revision --autogenerate -m "initial"
├── 移除 connection.py 中的 initialize_schema()
└── lifespan 中改为 alembic upgrade head
```

**关键改动文件**：`app/database/connection.py`, 新增 `app/models/db_models.py`, `alembic/`

#### 2.3 Repository 层安全化
**现状**：f-string 拼接 SQL（`repositories.py:98`），直接写裸 SQL。
**目标**：参数化查询 + SQL 注入彻底消除。

```
改造内容：
├── repositories.py 中所有 f-string SQL → 参数化
│   ├── L98: f"UPDATE sessions SET {', '.join(updates)}" → 白名单字段映射
│   └── AgentMemoryRepository.update 同理
├── 长远：迁移到 SQLAlchemy ORM，消除手写 SQL
└── 新增 app/database/base.py — 通用 CRUD 基类
```

**关键改动文件**：`app/database/repositories.py`

#### 2.4 事务一致性
**现状**：每次 execute 后手动 commit，无事务边界。
**目标**：事务上下文管理器。

```python
# app/database/connection.py
async def transaction(self):
    """事务上下文管理器"""
    conn = await self.acquire()
    try:
        yield conn
        await self.commit()
    except Exception:
        await self.rollback()
        raise
    finally:
        self.release(conn)
```

---

### 领域 3：架构与依赖注入 [P1]

#### 3.1 依赖注入容器
**现状**：所有服务在 `app/main.py` 顶层实例化，API 层靠 `from app.main import xxx` 延迟导入获取。
**目标**：FastAPI 原生 Depends + 应用状态管理。

```
改造内容：
├── app/container.py（新增）— 服务容器
│   ├── class ServiceContainer:
│   │   ├── db, session_repo, message_repo, ...
│   │   └── 所有服务实例
│   └── 延迟初始化（lifespan 中 setup）
├── app/main.py → 将服务实例存入 app.state
│   └── app.state.container = ServiceContainer(...)
├── app/api/deps.py → 从 request.app.state 获取服务
│   └── def get_db(request) → request.app.state.container.db
└── 消除所有 from app.main import xxx 反模式
```

**关键改动文件**：`app/main.py`, `app/api/chat.py`（及其他 API 文件）, 新增 `app/container.py`

#### 3.2 消除循环导入
**现状**：chat.py 内部 7+ 处延迟 `from app.main import` / `from app.services.xxx import`。
**目标**：模块依赖关系单向化。

```
改造方向：
├── API 层 → 只依赖 deps.py（依赖注入）
├── Service 层 → 只依赖 database/ 和 models/
├── Core 层 → 只依赖 services/（通过接口）
└── main.py → 只做组装，不被任何模块 import
```

#### 3.3 清理残留文件
```
删除：
├── app/core/execution.py.backup
├── app/core/execution.py.utf8
├── app/core/execution_thinking_patch.txt
└── 重复的 llm_service.py shim（app/services/llm_service.py）
    → 已有 app/services/llm/service.py，shim 只需保留 re-export
```

---

### 领域 4：可观测性 [P1]

#### 4.1 结构化日志
**现状**：`logging.info(f"...")` 纯文本，无 trace_id。
**目标**：JSON 格式 + request_id 关联。

```python
# app/core/logging.py（新增）
import structlog

processor_chain = [
    structlog.contextvars.merge_contextvars,   # 绑定 request_id
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.JSONRenderer(),        # JSON 输出
]

# FastAPI 中间件：每个请求生成 request_id 绑定到 contextvars
```

**关键改动文件**：新增 `app/core/logging.py`, 改造 `main.py` lifespan

#### 4.2 健康检查与就绪探针
**现状**：`/health` 端点存在但不区分 liveness/readiness。
**目标**：K8s 兼容的健康检查。

```
├── GET /health/live  → 进程存活（始终 200）
├── GET /health/ready → 依赖就绪（检查 DB、LLM、MCP）
└── GET /health/startup → 启动完成
```

#### 4.3 Prometheus 指标
**现状**：无。
**目标**：核心指标暴露。

```
改造内容：
├── 引入 prometheus-fastapi-instrumentator
├── 自动采集：请求量、延迟、错误率
├── 自定义指标：
│   ├── llm_request_duration_seconds（LLM 调用延迟）
│   ├── tool_call_duration_seconds（工具调用延迟）
│   ├── active_websocket_connections（活跃连接数）
│   └── mcp_server_connection_status（MCP 连接状态）
└── GET /metrics 端点
```

---

### 领域 5：测试 [P1]

#### 5.1 测试基础设施
**现状**：零自动化测试。
**目标**：核心路径覆盖率 > 60%。

```
新增目录结构：
tests/
├── conftest.py          — fixtures（test DB, mock LLM, test client）
├── unit/
│   ├── test_security.py — JWT 生成/验证、密码哈希
│   ├── test_repositories.py — Repository CRUD
│   ├── test_decision.py — 决策引擎
│   └── test_config.py   — 配置解析
├── integration/
│   ├── test_chat_api.py — 聊天 API（含 WebSocket）
│   ├── test_auth.py     — 认证流程
│   └── test_tools.py    — 工具调用
└── e2e/
    └── test_full_flow.py — 完整对话流程
```

#### 5.2 Mock 策略
```
├── LLM 服务 → 预录制响应 fixture（避免真实 API 调用）
├── MCP 服务 → mock httpx.AsyncClient
├── 数据库 → 内存 SQLite（:memory:）
└── 时间 → freezegun 或 mock beijing_now
```

---

### 领域 6：部署与 CI/CD [P2]

#### 6.1 Docker 化
```dockerfile
# Dockerfile（新增）
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev
COPY app/ app/
COPY main.py main.py
COPY skills/ skills/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml（新增）
services:
  app:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes: ["./data:/app/data"]  # SQLite + ChromaDB 持久化
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/ready"]
      interval: 30s
      timeout: 10s
      retries: 3
```

#### 6.2 CI Pipeline
```yaml
# .github/workflows/ci.yml（新增）
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff check app/ tests/
      - run: mypy app/
      - run: pytest --cov=app --cov-fail-under=60
```

#### 6.3 代码质量工具
```
替换 black+isort → ruff（更快，功能合并）
新增：
├── ruff check（lint + format）
├── mypy（类型检查，strict 模式渐进启用）
└── pre-commit hooks
```

---

### 领域 7：代码质量与规范 [P2]

#### 7.1 统一异常处理
**现状**：每个 API 端点独立 try/except，错误格式不一致。
**目标**：全局异常处理器 + 标准错误格式。

```python
# app/core/exceptions.py（新增）
class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 500):
        self.code = code
        self.message = message
        self.status = status

# app/main.py
@app.exception_handler(AppError)
async def app_error_handler(request, exc):
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message}}
    )
```

#### 7.2 配置验证
**现状**：`Settings` 允许 `extra="ignore"`，拼错的配置项静默忽略。
**目标**：启动时校验必要配置。

```python
# app/config.py
model_config = SettingsConfigDict(
    extra="forbid",  # 拼错就报错
)

@model_validator(mode="after")
def validate_config(self):
    if self.APP_DEBUG and self.APP_HOST == "0.0.0.0":
        logger.warning("Debug mode with public binding — not for production")
    return self
```

#### 7.3 类型标注补全
**现状**：大量 `Any`, `Optional[Dict]`，mypy 无法检查。
**目标**：关键模块添加严格类型。

```
优先级：
├── P0: API 层请求/响应模型（已有 Pydantic，补全缺失字段）
├── P1: Service 层方法签名（返回值类型明确）
└── P2: Core 层执行引擎（ExecutionPlan, ExecutionStep 已有 dataclass）
```

#### 7.4 国际化统一
**现状**：中英混杂（代码注释中文、日志中文、API 文档中文、变量名英文）。
**目标**：统一规范。

```
规则：
├── 代码/变量/函数名 → 英文
├── 日志 → 英文（便于日志系统分析）
├── API 文档 → 中文（面向国内用户）
└── 面向用户的提示语 → 中文
```

---

## 三、实施路线图

### Phase 1：安全加固（1-2 周）
| 编号 | 项 | 优先级 | 预估 |
|------|-----|--------|------|
| 1.1 | JWT 认证体系 | P0 | 3d |
| 1.2 | 密码安全升级 | P0 | 1d |
| 1.3 | WebSocket 认证 | P0 | 1d |
| 1.4 | CORS + 安全头 | P0 | 0.5d |
| 1.5 | 速率限制 | P0 | 0.5d |
| 1.6 | 文件系统沙箱 | P0 | 1d |

### Phase 2：数据层加固（1-2 周）
| 编号 | 项 | 优先级 | 预估 |
|------|-----|--------|------|
| 2.1 | 数据库连接池 | P0 | 2d |
| 2.2 | Alembic 迁移系统 | P0 | 2d |
| 2.3 | Repository 安全化 | P0 | 1d |
| 2.4 | 事务一致性 | P1 | 1d |

### Phase 3：架构改造（2 周）
| 编号 | 项 | 优先级 | 预估 |
|------|-----|--------|------|
| 3.1 | 依赖注入容器 | P1 | 3d |
| 3.2 | 消除循环导入 | P1 | 2d |
| 3.3 | 清理残留文件 | P2 | 0.5d |

### Phase 4：可观测性与测试（2 周）
| 编号 | 项 | 优先级 | 预估 |
|------|-----|--------|------|
| 4.1 | 结构化日志 | P1 | 2d |
| 4.2 | 健康检查探针 | P1 | 0.5d |
| 4.3 | Prometheus 指标 | P1 | 1d |
| 5.1 | 测试基础设施 | P1 | 3d |
| 5.2 | 核心路径测试 | P1 | 3d |

### Phase 5：部署与质量（1 周）
| 编号 | 项 | 优先级 | 预估 |
|------|-----|--------|------|
| 6.1 | Docker 化 | P2 | 1d |
| 6.2 | CI Pipeline | P2 | 1d |
| 6.3 | 代码质量工具 | P2 | 1d |
| 7.1 | 统一异常处理 | P2 | 1d |
| 7.2 | 配置验证 | P2 | 0.5d |

---

## 四、风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| JWT 改造需前后端同步 | 前端改动大 | 先做 API 兼容层，双模式并行 |
| Alembic 迁移需锁表 | 线上切换可能中断 | 维护窗口执行，先备份 |
| 依赖注入重构范围大 | 可能引入新 bug | 逐模块迁移，每步有测试 |
| SQLite → PostgreSQL | 查询语法差异 | 用 SQLAlchemy ORM 抽象，渐进迁移 |
| 结构化日志影响调试 | 开发体验变化 | 开发环境保留文本格式 |

---

## 五、验收标准

### 安全验收
- [ ] 未认证请求无法访问任何 API（除 /login, /health）
- [ ] WebSocket 未带 token 立即断开
- [ ] 密码文件泄露后无法反推明文（bcrypt）
- [ ] 文件系统工具无法读取 base_path 之外的文件
- [ ] 单 IP 登录失败 5 次后锁定 1 分钟

### 数据验收
- [ ] 数据库 schema 变更通过 alembic upgrade 执行
- [ ] 并发 50 连接无数据丢失
- [ ] 所有 SQL 均为参数化查询

### 可观测性验收
- [ ] 所有日志含 request_id，可按请求链路追踪
- [ ] /metrics 端点暴露核心指标
- [ ] /health/ready 正确反映依赖状态

### 测试验收
- [ ] pytest 通过，核心路径覆盖率 > 60%
- [ ] CI pipeline 全绿
