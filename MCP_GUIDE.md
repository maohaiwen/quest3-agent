# MCP 工具调用使用指南

## 概述

本应用已集成 MCP (Model Context Protocol) 工具调用能力，支持以下功能：

1. **本地文件系统工具** - 内置支持文件读写和目录操作
2. **MCP 服务器连接** - 支持连接到外部 MCP 服务器（如阿里云 MCP）
3. **通用工具调用** - 支持任意类型的 MCP 工具

## 已实现的功能

### 本地工具

以下工具已内置并自动启用：

- `read_file` - 读取文件内容
- `write_file` - 写入文件
- `list_directory` - 列出目录内容

### API 端点

新增以下 API 端点用于 MCP 管理：

- `GET /api/mcp/tools` - 列出所有可用工具
- `GET /api/mcp/tools/{tool_name}` - 获取特定工具信息
- `POST /api/mcp/call` - 调用工具
- `POST /api/mcp/connect` - 连接到 MCP 服务器
- `POST /api/mcp/disconnect` - 断开 MCP 服务器连接

- `GET /tools` - 获取工具描述和状态信息（已更新）

## 配置

### 环境变量配置

在 `.env` 文件中添加以下配置：

```bash
# MCP 服务器 URL（可选）
# 如果不配置，则只使用本地工具
MCP_SERVER_URL=http://your-mcp-server:port
```

### 连接阿里云 MCP 示例

```bash
MCP_SERVER_URL=https://aliyun-mcp.example.com
```

## 使用方法

### 1. 启动应用

```bash
python main.py
```

### 2. 测试工具状态

访问健康检查端点：

```bash
curl http://localhost:8000/health
```

返回示例：
```json
{
  "status": "healthy",
  "llm_configured": true,
  "vector_store_available": true,
  "mcp_connected": false
}
```

### 3. 查看可用工具

```bash
curl http://localhost:8000/api/mcp/tools
```

### 4. 在聊天中使用工具

在聊天界面中，你可以要求 AI 执行需要工具的任务，例如：

```
请读取 README.md 文件的内容
```

```
请列出当前目录的文件
```

```
请创建一个名为 hello.txt 的文件，内容为 "Hello World"
```

### 5. 手动调用工具（通过 API）

```bash
curl -X POST http://localhost:8000/api/mcp/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "read_file",
    "arguments": {
      "file_path": "README.md"
    }
  }'
```

### 6. 动态连接 MCP 服务器

```bash
curl -X POST http://localhost:8000/api/mcp/connect \
  -H "Content-Type: application/json" \
  -d '{
    "server_url": "http://your-mcp-server:8080"
  }'
```

## 工具调用流程

1. 用户在聊天中发送消息
2. LLM 分析是否需要使用工具
3. 如果需要工具，LLM 发送工具调用请求
4. 系统执行相应工具
5. 工具结果返回给 LLM
6. LLM 基于工具结果生成最终响应

## 安全注意事项

1. **文件路径限制** - 本地文件工具默认在项目目录下操作
2. **输入验证** - 所有工具参数都会进行验证
3. **权限控制** - 建议在生产环境中添加身份验证

## 扩展自定义工具

要添加自定义工具，创建一个工具服务类并实现 `get_tools()` 方法：

```python
class CustomToolService:
    def __init__(self):
        pass

    async def my_custom_tool(self, param: str) -> str:
        # 实现你的工具逻辑
        return f"Result: {param}"

    def get_tools(self):
        return {
            "my_custom_tool": MCPTool(
                name="my_custom_tool",
                description="My custom tool",
                input_schema={
                    "type": "object",
                    "properties": {
                        "param": {"type": "string"}
                    },
                    "required": ["param"]
                },
                handler=self.my_custom_tool
            )
        }
```

然后在 `app/main.py` 中注册：

```python
from app.services.mcp_service import mcp_tool_manager
custom_service = CustomToolService()
mcp_tool_manager.register_local_service("Custom", custom_service)
```

## 故障排查

### 工具无法调用

1. 检查 LLM 是否配置了 API 密钥
2. 检查健康检查端点的 `mcp_connected` 状态
3. 查看应用日志中的错误信息

### MCP 服务器连接失败

1. 确认服务器 URL 正确
2. 检查网络连接
3. 确认 MCP 服务器正在运行

### 工具执行错误

1. 查看工具参数格式是否正确
2. 检查工具描述中的参数要求
3. 确认有足够的权限执行操作

## 下一步

- [ ] 添加更多本地工具（数据库查询、API 调用等）
- [ ] 实现工具调用历史记录
- [ ] 添加工具调用权限控制
- [ ] 支持多 MCP 服务器同时连接
- [ ] 添加工具执行超时控制
