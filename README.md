# Quest3 Agent

多智能体协作平台，支持多种协作模式、MCP工具集成、技能系统和深度思考。

## 功能特性

### 智能体管理
- 多智能体配置：每个智能体可独立配置模型、system_prompt、执行模式、工具、MCP服务器
- 执行模式：direct（直接对话）、plan（规划执行）、react（推理行动）、react_cot（推理+思维链）、thinking_while_doing（边想边做）
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
- 短期记忆：会话级别的消息历史管理
- 长期记忆：基于ChromaDB向量数据库的语义搜索记忆

### A2A协议
- 支持Google Agent-to-Agent协议
- 本地Agent直接调用，远程Agent通过HTTP调用

## 前端页面

| 页面 | 路径 | 功能 |
|------|------|------|
| 主页 | `/static/index.html` | 聊天对话界面 |
| 智能体管理 | `/static/agent_manager.html` | 创建/编辑/删除智能体 |
| 协作Playground | `/static/collaboration_playground.html` | 可视化多智能体协作 |
| 协作编辑器 | `/static/collaboration_editor.html` | 配置协作模式和智能体 |
| MCP管理 | `/static/mcp_manager.html` | 管理MCP服务器连接 |
| 技能管理 | `/static/skill_manager.html` | 管理和编辑技能 |

## 技术栈

- **Web框架**: FastAPI + Uvicorn
- **LLM**: 火山引擎（Volcengine/DeepSeek）+ Anthropic Claude
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

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置必要的API密钥：

```env
# 火山引擎（深度思考 + 工具调用）
VOLCENGINE_API_KEY=your_volcengine_api_key
VOLCENGINE_MODEL=deepseek-v3-2-251201

# 网络搜索
WEB_SEARCH_API_KEY=your_web_search_api_key
```

### 4. 启动应用

```bash
python main.py
```

应用将在 `http://localhost:8000` 启动。

## 项目结构

```
quest3-agent/
├── app/
│   ├── main.py                 # FastAPI应用入口
│   ├── config.py               # 配置管理
│   ├── api/                    # API接口层
│   │   ├── agents.py           # 智能体CRUD
│   │   ├── chat.py             # 聊天对话
│   │   ├── collaborations.py   # 多智能体协作
│   │   ├── a2a.py              # A2A协议端点
│   │   ├── mcp.py              # MCP工具调用
│   │   ├── mcp_servers.py      # MCP服务器管理
│   │   ├── skills.py           # 技能管理
│   │   ├── sessions.py         # 会话管理
│   │   └── memory.py           # 记忆管理
│   ├── core/                   # 核心执行引擎
│   │   ├── react_cot_executor.py    # ReAct+CoT执行器
│   │   ├── react_executor.py        # ReAct执行器
│   │   ├── decision.py              # 任务决策引擎
│   │   ├── execution.py             # 执行引擎
│   │   ├── strategy_router.py       # 策略路由
│   │   ├── thinking_while_doing_executor.py  # 边想边做执行器
│   │   └── tool_manager.py          # 统一工具管理器
│   ├── models/                 # 数据模型
│   │   ├── agent.py            # 智能体模型
│   │   ├── collaboration.py    # 协作模型
│   │   ├── a2a.py              # A2A协议模型
│   │   ├── skill.py            # 技能模型
│   │   ├── chat.py             # 聊天模型
│   │   ├── session.py          # 会话模型
│   │   └── memory.py           # 记忆模型
│   ├── services/               # 服务层
│   │   ├── collaboration_engine.py  # 协作执行引擎（5种模式）
│   │   ├── collaboration_service.py # 协作配置管理
│   │   ├── a2a_adapter.py            # A2A协议适配器
│   │   ├── agent_registry.py         # 智能体注册表
│   │   ├── agent_service.py          # 智能体服务
│   │   ├── llm_service.py            # LLM服务（火山引擎）
│   │   ├── mcp_pool.py               # MCP服务器连接池
│   │   ├── mcp_service.py            # MCP服务
│   │   ├── planning_chat_service.py  # 规划聊天服务
│   │   ├── memory_service.py         # 记忆服务
│   │   └── vector_service.py         # 向量服务
│   ├── skills/                 # 技能系统
│   │   ├── registry.py         # 技能注册表
│   │   ├── loader.py           # 技能加载器
│   │   ├── executor.py         # 技能执行器
│   │   ├── writer.py           # 技能编写器
│   │   ├── importer.py         # GitHub技能导入
│   │   └── templates.py        # 技能模板
│   ├── tools/                  # 本地工具
│   │   ├── web_search.py       # 网络搜索（火山引擎）
│   │   ├── filesystem.py       # 文件系统操作
│   │   └── base.py             # 工具基类
│   └── database/               # 数据库层
│       ├── connection.py       # 数据库连接
│       ├── repositories.py     # 通用仓储
│       ├── mcp_schema.py       # MCP数据表
│       └── skill_repository.py # 技能数据仓储
├── skills/                     # 技能文件
│   ├── builtin/                # 内置技能
│   └── user/                   # 用户自定义技能
├── static/                     # 前端静态文件
├── doc/                        # 设计文档
├── docs/                       # 使用文档
├── main.py                     # 应用入口
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
- `GET /api/collaborations/templates/list` - 列出协作模板

### 聊天
- `POST /api/chat/chat` - 发送聊天消息
- `WS /api/chat/stream` - WebSocket流式聊天

### MCP
- `GET /api/mcp/servers` - 列出MCP服务器
- `POST /api/mcp/servers` - 添加MCP服务器
- `POST /api/mcp/servers/{id}/connect` - 连接MCP服务器
- `POST /api/mcp/tools/call` - 调用MCP工具

### 技能
- `GET /api/skills` - 列出所有技能
- `POST /api/skills` - 创建技能
- `POST /api/skills/import/github` - 从GitHub导入技能

## 许可证

MIT License
