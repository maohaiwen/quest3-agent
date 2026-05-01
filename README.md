# Quest3 Agent

AI智能体聊天应用，支持多轮对话和长短期记忆。

## 功能特性

- 智能对话：基于Anthropic Claude API的智能对话
- 多轮对话：支持上下文保持的多轮对话
- 短期记忆：会话级别的消息历史管理
- 长期记忆：基于向量数据库的语义搜索记忆
- WebSocket支持：实时流式对话
- 简单易用：提供简洁的HTML测试页面

## 技术栈

- **Web框架**: FastAPI
- **LLM提供商**: Anthropic Claude API
- **向量数据库**: ChromaDB
- **数据库**: SQLite (aiosqlite)
- **Python版本**: 3.12+

## 安装

### 1. 克隆仓库

```bash
git clone <repository-url>
cd quest3-agent
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# or
source .venv/bin/activate  # Linux/Mac
```

### 3. 安装依赖

```bash
pip install -e .
```

### 4. 配置环境变量

复制环境变量示例文件并配置：

```bash
copy .env.example .env  # Windows
# or
cp .env.example .env  # Linux/Mac
```

编辑 `.env` 文件，设置你的Anthropic API密钥：

```env
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

## 运行

启动应用：

```bash
python main.py
```

应用将在 `http://localhost:8000` 启动。

## 访问

### 测试页面

打开浏览器访问测试页面：
```
http://localhost:8000/static/index.html
```

### API文档

自动生成的API文档：
```
http://localhost:8000/docs
```

### 健康检查

```
http://localhost:8000/health
```

## API接口

### 聊天接口

- `POST /api/chat/chat` - 发送聊天消息
- `WS /api/chat/stream` - WebSocket流式聊天

### 会话管理

- `POST /api/sessions/create` - 创建新会话
- `GET /api/sessions/{session_id}` - 获取会话信息
- `GET /api/sessions/{session_id}/history` - 获取会话历史
- `PUT /api/sessions/{session_id}` - 更新会话
- `DELETE /api/sessions/{session_id}` - 删除会话

### 记忆管理

- `POST /api/memory/store` - 存储长期记忆
- `GET /api/memory/search` - 搜索记忆
- `DELETE /api/memory/{memory_id}` - 删除记忆

## 项目结构

```
quest3-agent/
├── app/                    # 应用主目录
│   ├── main.py            # FastAPI应用入口
│   ├── config.py          # 配置管理
│   ├── api/               # API接口
│   ├── core/              # 核心业务逻辑
│   ├── models/            # 数据模型
│   ├── database/          # 数据库层
│   └── services/          # 服务层
├── static/                # 静态文件
│   └── index.html        # 测试页面
├── main.py               # 应用入口
└── pyproject.toml        # 项目配置
```

## 开发

### 代码格式化

```bash
black .
isort .
```

### 类型检查

```bash
mypy app/
```

### 运行测试

```bash
pytest
```

## 许可证

MIT License
