# Agent 配置 Skill 使用指南

## 概述

现在系统支持在创建/配置 Agent 时，选择以下内容：
- **Skills**：Agent 可以使用的技能（代码审查、文档生成等）
- **Tools**：Agent 可以使用的工具（文件操作、Web 搜索等）
- **MCP Servers**：Agent 可以连接的 MCP 服务器

Agent 选择了哪些，就只能使用哪些！

---

## 快速开始

### 1. 创建 Agent

使用 `POST /api/agents` 接口：

```python
import httpx
import asyncio

async def create_agent():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/agents",
            json={
                "name": "代码助手",
                "description": "专门用于代码审查和文档生成的助手",
                "type": "coder",
                "execution_mode": "plan",
                "system_prompt": "你是一个专业的开发助手。",
                "skills": ["code_reviewer", "doc_generator"],
                "tools": ["filesystem_read", "filesystem_write"],
                "mcp_servers": ["my-mcp-server-1"],
                "temperature": 0.7,
                "priority": 10
            }
        )
        print(response.json())

asyncio.run(create_agent())
```

### 2. 获取可用的 Skills

使用 `GET /api/skills` 或 `/api/skills/summaries`：

```python
async def list_skills():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://localhost:8000/api/skills/summaries")
        summaries = response.json()
        for name, summary in summaries.items():
            print(f"Skill: {name}")
            print(f"  Description: {summary['description']}")
            print(f"  Tags: {summary['tags']}")
```

### 3. 在聊天中使用 Agent

使用 `WS /api/chat/stream`：

```json
{
    "session_id": "my-session-123",
    "agent_id": "agent-uuid-here",
    "message": "帮我审查一下 main.py 文件"
}
```

系统会自动把 Agent 的 Skills 信息注入到系统提示词中！

---

## API 参考

### 创建 Agent

**POST /api/agents**

请求体：
```json
{
    "name": "string (required)",
    "description": "string",
    "type": "chat | coder | researcher | custom",
    "execution_mode": "plan | react | react_cot | thinking_while_doing | direct",
    "system_prompt": "string",
    "model": "string",
    "temperature": 0.7,
    "max_tokens": 2000,
    "skills": ["skill_name_1", "skill_name_2"],
    "tools": ["tool_name_1", "tool_name_2"],
    "mcp_servers": ["server_id_1", "server_id_2"],
    "enabled": true,
    "priority": 10,
    "thinking_effort": "low | medium | high",
    "max_react_steps": 20
}
```

### 更新 Agent

**PUT /api/agents/{agent_id}**

请求体和创建类似，但字段都是可选的。

### 获取 Agent

**GET /api/agents/{agent_id}**

响应示例：
```json
{
    "id": "agent-uuid",
    "name": "代码助手",
    "description": "专门用于代码审查和文档生成的助手",
    "type": "coder",
    "execution_mode": "plan",
    "system_prompt": "你是一个专业的开发助手。",
    "skills": ["code_reviewer", "doc_generator"],
    "tools": ["filesystem_read", "filesystem_write"],
    "mcp_servers": [{"server_id": "my-mcp-server-1", "enabled": true}],
    "enabled": true,
    "priority": 10
}
```

### Skill 相关 API

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /api/skills | 获取所有 Skills |
| GET | /api/skills/summaries | 获取 Skill 摘要（节省 token） |
| GET | /api/skills/{skill_name} | 获取单个 Skill |
| GET | /api/skills/agent/{agent_id} | 获取 Agent 的 Skills |
| POST | /api/skills/agent/{agent_id}/link | 关联 Skill 到 Agent |
| POST | /api/skills/agent/{agent_id}/unlink | 取消关联 |
| GET | /api/skills/agent/{agent_id}/system-prompt | 获取 Skill 系统提示词 |

---

## Skill 系统提示词注入机制

当 Agent 有关联的 Skills 时，系统会自动在 Agent 的 system_prompt 后添加以下内容：

```
【可用技能】
- code_reviewer: 代码审查助手，分析代码质量并提供改进建议 (tags: ['code', 'review', 'programming'])
- doc_generator: 文档生成助手，帮助创建技术文档和说明 (tags: ['documentation', 'writing'])

当用户的请求匹配某个技能时，先调用 load_skill 工具加载该技能的完整说明书。
```

然后 Agent 可以决定是否使用某个 Skill，如果需要，就用 `load_skill` 工具加载完整的 Skill 说明。

---

## 完整示例

### 示例 1：创建具有多种能力的 Agent

```python
import httpx
import asyncio

async def create_complete_agent():
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # 1. 获取可用的 skills
        skills_response = await client.get("/api/skills/summaries")
        print("Available skills:", skills_response.json())

        # 2. 创建 agent
        agent_data = {
            "name": "全能研究助手",
            "description": "可以进行代码审查、网络调研和文档生成的助手",
            "type": "researcher",
            "execution_mode": "plan",
            "system_prompt": "你是一个专业的研究助手。",
            "skills": ["code_reviewer", "web_research", "doc_generator"],
            "tools": ["web_search", "filesystem_read", "filesystem_write"],
            "mcp_servers": ["mcp-server-github", "mcp-server-database"],
            "temperature": 0.7,
            "priority": 10
        }

        agent_response = await client.post("/api/agents", json=agent_data)
        agent = agent_response.json()
        print(f"Created agent: {agent['id']}")
        print(f"Skills: {agent['skills']}")

        # 3. 获取 skill 系统提示词
        prompt_response = await client.get(f"/api/skills/agent/{agent['id']}/system-prompt")
        print("System prompt addition:", prompt_response.json())

        return agent

if __name__ == "__main__":
    asyncio.run(create_complete_agent())
```

### 示例 2：更新 Agent 的 Skills

```python
async def update_agent_skills(agent_id):
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # 只更新 skills
        update_data = {
            "skills": ["code_reviewer", "web_research"]  # 移除 doc_generator
        }
        response = await client.put(f"/api/agents/{agent_id}", json=update_data)
        updated_agent = response.json()
        print(f"Updated skills: {updated_agent['skills']}")
```

---

## Skill 触发机制

系统还支持基于消息内容自动匹配合适的 Skill：

1. **关键词匹配**：如果消息包含 Skill 的 tag 或关键词
2. **意图匹配**（待实现）：使用 LLM 判断消息意图是否匹配 Skill
3. **正则匹配**：如果消息符合 Skill 的正则模式

使用 SkillTriggerManager：

```python
from app.skills.trigger import get_trigger_manager

trigger_manager = get_trigger_manager()
matches = await trigger_manager.find_matching_skills(
    "帮我审查一下这个代码",
    session_id="my-session"
)

for skill, confidence, trigger in matches:
    print(f"{skill.name}: {confidence:.2f}")
```

---

## 数据库架构

### agents 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | Agent ID |
| name | TEXT | 名称 |
| skills | - | (不在本表，通过关联表) |

### agent_skills 表
| 字段 | 类型 | 说明 |
|------|------|------|
| agent_id | TEXT | Agent ID |
| skill_id | TEXT | Skill ID |
| enabled | INTEGER | 是否启用 |
| priority | INTEGER | 优先级 |
| created_at | TEXT | 创建时间 |

### skills 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | Skill ID |
| name | TEXT | 名称 |
| description | TEXT | 描述 |
| requirements | TEXT | Python 依赖（JSON 数组） |
| tags | TEXT | 标签（JSON 数组） |
| tools | TEXT | 依赖的工具（JSON 数组） |
| skill_content | TEXT | 完整的 skill.md 内容 |
| entrypoint | TEXT | Python 入口点（可选） |

---

## 最佳实践

1. **Skill 粒度适中**：每个 Skill 专注于一个具体任务
2. **Skill 描述清晰**：描述要说明 Skill 能做什么，不能做什么
3. **合理使用 Tags**：Tags 用于触发匹配，要准确
4. **Skill 数量控制**：一个 Agent 关联 3-5 个 Skill 比较合适
5. **更新 Skill 配置**：Skill 的内容更新后，不需要重新关联 Agent

---

## 常见问题

### Q: Agent 创建后，Skill 系统提示词没有生效？

A: 检查两点：
1. Skill 已正确关联到 Agent（用 `GET /api/skills/agent/{agent_id}` 验证）
2. SkillRegistry 已同步（调用 `GET /api/skills/agent/{agent_id}/system-prompt` 验证）

### Q: 如何创建自定义 Skill？

A: 在 `user_skills/` 目录下创建文件夹，包含 `skill.md`（可选 `main.py`），然后调用 `POST /api/skills/reload`。

### Q: Skill 里的 Python 代码如何调用？

A: 使用 SkillExecutor：
```python
from app.skills.executor import get_skill_executor

executor = get_skill_executor()
result = await executor.execute(
    "my_skill",
    {"input_data": "...", "config": {...}},
    session_id="my-session"
)
```
