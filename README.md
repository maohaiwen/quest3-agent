# Quest3 Agent

多智能体协作平台，支持多种协作模式、MCP工具集成、技能系统、在线配置和用户管理。

## 功能特性

### 智能体管理
- 多智能体配置：每个智能体可独立配置模型、system_prompt、执行模式、工具、MCP服务器
- 执行模式：direct（直接对话）、plan（规划执行）、react（推理行动）、react_cot（推理+思维链）
- 深度思考：集成火山引擎深度推理，支持 configurable reasoning effort

### 多智能体协作
- **监督者模式（Supervisor）**：一个总监拆分任务，多个子Agent并行/串行执行，最后汇总
- **流水线模式（Pipeline）**：多个Agent按顺序依次处理，上一步输出作为下一步输入
- **投票集成模式（Voting）**：多个Agent独立回答同一问题，聚合器汇总出最终答案
- **生成-判别对抗模式（Adversarial）**：生成器产出内容，判别器校验，循环优化
- **博弈模式（Game）**：支持同时行动和轮流行动，裁判裁决每轮胜负
- 实时SSE流式事件，前端可视化协作过程

### MCP工具集成
- MCP服务器池管理，支持标准MCP和Streamable HTTP协议
- 代码解释器（阿里云DashScope）：Python沙箱执行，可获取和分析数据
- 统一工具管理器：本地工具、MCP工具、技能工具统一接口
- 工具按智能体白名单+MCP服务器自动过滤

### 技能系统（Skill）
- 内置技能：代码审查、文档生成、网络研究
- 自定义技能：支持编写skill.md和入口脚本（main.py/main.sh）
- 技能可关联到智能体，自动注入system prompt
- 支持从GitHub仓库导入技能

### 记忆系统
- 工作记忆：会话级别的消息历史管理与自动摘要
- 长期记忆：基于ChromaDB向量数据库的Agent级语义搜索记忆
- 参数可在线配置（最大消息数、摘要阈值、重要性阈值等）

### 在线设置与用户管理
- 系统设置页面：LLM/记忆/搜索参数在线编辑，修改后热生效
- API Key 等敏感字段脱敏显示
- 用户管理：admin/普通用户角色，admin 可修改配置
- 首次使用检测：未配置 API Key 时弹窗引导到设置页
- 默认账号：admin / admin123

### A2A协议
- 支持Google Agent-to-Agent协议
- 本地Agent直接调用，远程Agent通过HTTP调用

## 前端页面

| 页面 | 路径 | 功能 |
|------|------|------|
| 登录 | `/static/login.html` | 用户登录 |
| 智能体管理 | `/static/agent_manager.html` | 创建/编辑/删除智能体，聊天入口 |
| 协作Playground | `/static/collaboration_playground.html` | 可视化多智能体协作 |
| 协作编辑器 | `/static/collaboration_editor.html` | 配置协作模式和智能体 |
| MCP管理 | `/static/mcp_manager.html` | 管理MCP服务器连接 |
| 技能管理 | `/static/skill_manager.html` | 管理和编辑技能 |
| 系统设置 | `/static/settings.html` | 在线配置LLM/记忆/搜索，用户管理 |
| 移动端 | `/m` | H5移动端页面 |

## 技术栈

- **Web框架**: FastAPI + Uvicorn
- **LLM**: 火山引擎（Volcengine/DeepSeek）
- **向量数据库**: ChromaDB
- **数据库**: SQLite (aiosqlite)
- **MCP协议**: 标准MCP + Streamable HTTP
- **Python版本**: 3.12+

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/maohaiwen/quest3-agent.git
cd quest3-agent
```

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -e .
```

### 3. 启动应用

```bash
python main.py
```

应用将在 `http://localhost:8000` 启动。

### 4. 首次配置

1. 访问 `http://localhost:8000`，使用默认账号登录：**admin / admin123**
2. 首次登录会提示未配置，点击前往设置页
3. 填写火山引擎 API Key，点击保存
4. 点击"测试 LLM 连接"验证配置
5. 返回主页开始使用

> 配置存储在数据库中，也可通过 `.env` 文件预设（数据库配置优先）

## 项目结构

```
quest3-agent/
├── app/
│   ├── main.py                 # FastAPI应用入口
│   ├── config.py               # 配置管理（支持数据库热刷新）
│   ├── api/                    # API接口层
│   │   ├── agents.py           # 智能体CRUD
│   │   ├── chat.py             # 聊天对话
│   │   ├── collaborations.py   # 多智能体协作
│   │   ├── a2a.py              # A2A协议端点
│   │   ├── mcp.py              # MCP工具调用
│   │   ├── mcp_servers.py      # MCP服务器管理
│   │   ├── skills.py           # 技能管理
│   │   ├── sessions.py         # 会话管理
│   │   ├── memory.py           # 记忆管理
│   │   ├── settings.py         # 系统设置API
│   │   └── users.py            # 用户管理API
│   ├── core/                   # 核心执行引擎
│   │   ├── react_cot_executor.py    # ReAct+CoT执行器
│   │   ├── react_executor.py        # ReAct执行器
│   │   ├── decision.py              # 任务决策引擎
│   │   ├── execution.py             # 执行引擎
│   │   ├── strategy_router.py       # 策略路由
│   │   └── tool_manager.py          # 统一工具管理器
│   ├── models/                 # 数据模型
│   ├── services/               # 服务层
│   │   ├── collaboration/           # 协作引擎（5种模式）
│   │   ├── agent_service.py         # 智能体服务
│   │   ├── agent_memory_service.py  # Agent长期记忆
│   │   ├── session_working_memory.py# 会话工作记忆
│   │   ├── llm_service.py           # LLM服务（火山引擎）
│   │   ├── settings_service.py      # 配置管理服务
│   │   ├── user_service.py          # 用户管理服务
│   │   ├── mcp_pool.py              # MCP服务器连接池
│   │   └── vector_service.py        # 向量服务
│   ├── skills/                 # 技能系统
│   ├── tools/                  # 本地工具
│   └── database/               # 数据库层
├── static/                     # 前端静态文件
│   ├── core/                   # 核心JS（Router/Auth/API）
│   ├── modules/                # 功能模块（Chat/Agent/MCP）
│   └── components/             # UI组件
├── skills/                     # 技能文件
├── doc/                        # 设计文档
└── pyproject.toml              # 项目配置
```

## API概览

### 智能体
- `GET /api/agents` - 列出所有智能体
- `POST /api/agents` - 创建智能体
- `PUT /api/agents/{id}` - 更新智能体
- `DELETE /api/agents/{id}` - 删除智能体

### 多智能体协作
- `GET /api/collaborations` - 列出所有协作
- `POST /api/collaborations` - 创建协作
- `POST /api/collaborations/{id}/execute` - 执行协作（同步）
- `GET /api/collaborations/{id}/execute_sse` - 执行协作（SSE流式）

### 聊天
- `POST /api/chat/chat` - 发送聊天消息
- `POST /api/chat/stream` - 流式聊天

### MCP
- `GET /api/mcp/servers` - 列出MCP服务器
- `POST /api/mcp/servers` - 添加MCP服务器
- `POST /api/mcp/servers/{id}/connect` - 连接MCP服务器

### 技能
- `GET /api/skills` - 列出所有技能
- `POST /api/skills` - 创建技能
- `POST /api/skills/import/github` - 从GitHub导入技能

### 设置与用户
- `GET /api/settings` - 获取系统配置
- `PUT /api/settings` - 更新配置（需admin）
- `GET /api/settings/init-status` - 检查是否已初始化
- `POST /api/settings/test-llm` - 测试LLM连接
- `POST /api/users/login` - 用户登录
- `GET /api/users` - 用户列表（需admin）
- `POST /api/users` - 创建用户（需admin）

## 许可证

MIT License
