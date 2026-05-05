# Agent 级记忆系统设计文档

## 1. 概述

Quest3 Agent 的记忆系统采用 **Agent 级为主、Session 级为辅** 的两层架构，支持类似豆包的智能体记忆能力。每个 Agent 可独立开启长期记忆，实现跨会话的知识积累和偏好记忆。

### 核心能力

- **工作记忆**：当前对话上下文，支持自动摘要压缩
- **长期记忆**：Agent 级跨会话记忆，自动提取、语义搜索、重要性衰减
- **记忆开关**：Agent 级别控制 `enable_long_term_memory`，不是所有 Agent 都启用

---

## 2. 架构设计

```
┌─────────────────────────────────────────────────────┐
│                  SessionWorkingMemory                │
│  合并原有 MemoryService + ConversationContext        │
│  - 当前对话上下文 (最近 N 轮)                        │
│  - 自动摘要 (消息过多时压缩)                         │
│  - 召回的相关 Agent 记忆 (注入到上下文)               │
│  存储: 内存缓存 + SQLite 持久化                      │
├─────────────────────────────────────────────────────┤
│                  AgentMemoryService                  │
│  Agent 级长期记忆                                     │
│  - 自动记忆提取 (对话结束时 LLM 批量提取)             │
│  - 语义搜索 (ChromaDB, agent_{id} collection)        │
│  - 重要性分级 + 衰减                                 │
│  - 记忆整合 (去重/合并/压缩)                          │
│  存储: ChromaDB + SQLite agent_memories 表           │
└─────────────────────────────────────────────────────┘
```

### 数据流

```
用户消息 → SessionWorkingMemory (短期)
              ↓
         Agent 启用长期记忆？
           ├── 否 → 仅用短期记忆 → LLM
           └── 是 → AgentMemoryService.recall (语义搜索)
                    AgentMemoryService.get_agent_profile (画像)
                    ↓
                    注入记忆上下文到 system_prompt → LLM
                    ↓
              WebSocket 断开时
                    ↓
              AgentMemoryService.extract_and_store (批量提取)
```

---

## 3. 数据模型

### 3.1 agent_memories 表

```sql
CREATE TABLE agent_memories (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,           -- 关联 Agent
    session_id TEXT,                  -- 来源 Session (可选)
    content TEXT NOT NULL,            -- 记忆内容
    memory_type TEXT NOT NULL,        -- preference / fact / event / summary
    importance REAL DEFAULT 0.5,      -- 重要性 0.0-1.0
    access_count INTEGER DEFAULT 0,   -- 被召回次数
    source TEXT DEFAULT 'auto',       -- auto / manual
    metadata TEXT,                    -- 额外元数据 JSON
    created_at TEXT NOT NULL,
    last_accessed_at TEXT,            -- 最后访问时间 (用于衰减)
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
```

### 3.2 记忆类型

| 类型 | 说明 | 默认重要性范围 | 示例 |
|---|---|---|---|
| preference | 用户偏好/习惯 | 0.8-1.0 | "用户喜欢简短的回答" |
| fact | 重要事实 | 0.5-0.8 | "用户的项目使用 Python 3.12" |
| event | 值得记住的事件 | 0.3-0.5 | "用户上周讨论了数据库迁移" |
| summary | 对话摘要 | 0.3-0.5 | "讨论了API设计方案的对比" |

### 3.3 Agent 模型新增字段

`agents` 表新增 `enable_long_term_memory INTEGER DEFAULT 0`，对应 Agent 模型的 `enable_long_term_memory: bool`。

---

## 4. 核心组件

### 4.1 SessionWorkingMemory

**文件**: `app/services/session_working_memory.py`

替代原有的 `MemoryService` + `ConversationContext`，统一管理会话工作记忆。

| 方法 | 说明 |
|---|---|
| `add_message(session_id, role, content, reasoning_content)` | 添加消息 |
| `get_recent_messages(session_id, n)` | 获取最近 N 条消息 |
| `get_conversation_history(session_id, limit)` | 获取对话历史（含摘要） |
| `get_context_for_llm(session_id, model_version)` | 获取过滤后的 LLM 上下文 |
| `get_all_messages(session_id)` | 获取全部消息（用于记忆提取） |
| `maybe_summarize(session_id, agent_model)` | 检查并生成对话摘要 |
| `load_from_db(session_id, db_messages)` | 从数据库加载 |
| `clear_session(session_id)` | 清空会话记忆 |

**摘要机制**：当消息数超过 `MEMORY_SUMMARY_THRESHOLD`（默认30）时，自动将较早的消息压缩为摘要，保留最近 `MEMORY_SUMMARY_KEEP_RECENT`（默认10）条。摘要使用 Agent 配置的同一模型生成。

### 4.2 AgentMemoryService

**文件**: `app/services/agent_memory_service.py`

Agent 级长期记忆核心服务。

| 方法 | 说明 |
|---|---|
| `extract_and_store(agent_id, session_id, conversation_messages)` | 对话结束时批量提取记忆 |
| `recall(agent_id, query, n, min_importance)` | 语义搜索召回相关记忆 |
| `get_agent_profile(agent_id)` | 获取高重要性偏好/事实画像 |
| `store_manual(agent_id, content, memory_type, importance)` | 手动存储记忆 |
| `consolidate(agent_id)` | 记忆整合（去重/删除低价值） |
| `get_stats(agent_id)` | 记忆统计 |

**记忆提取**：对话结束时（WebSocket 断开），调用 LLM 批量分析完整对话，提取值得长期记住的信息。LLM 判断每条记忆的类型、重要性和是否是更新已有记忆。

**记忆召回**：通过 ChromaDB 语义搜索 + 重要性阈值过滤，召回与当前查询相关的记忆，注入到 Agent 的 system_prompt 中。

**重要性衰减**：

```
effective_importance = importance × e^(-λ × days_since_access) + min(access_count × 0.05, 0.3)
```

- 默认 λ = 0.05，半衰期约 14 天
- 被频繁访问的记忆衰减更慢

**记忆整合**：删除有效重要性 < 0.1 的记忆，合并内容相似的记忆。

---

## 5. 记忆提取 Prompt

```
分析以下完整对话记录，提取需要长期记住的信息。

规则：
- 用户明确表达的偏好/习惯 → type: "preference", importance: 0.8-1.0
- 重要事实/事件 → type: "fact", importance: 0.5-0.8
- 值得记住的上下文 → type: "event", importance: 0.3-0.5
- 闲聊/客套/临时信息 → 不提取
- 如果信息是对已有记忆的更新/纠正，标记 action: "update"

已有记忆摘要（避免重复）：
{existing_memories_summary}

完整对话记录：
{conversation}

以 JSON 数组输出，每项格式：
{"content": "记忆内容", "type": "preference|fact|event", "importance": 0.0-1.0, "action": "add|update"}
如果没有值得记住的信息，输出空数组 []
```

---

## 6. 记忆上下文注入

当 Agent 启用长期记忆时，聊天流程会：

1. **获取画像**：`get_agent_profile()` → 高重要性偏好和事实
2. **语义召回**：`recall(agent_id, user_message)` → 与当前话题相关的记忆
3. **注入 system_prompt**：

```
【记忆上下文】
关于对话对象的记忆：已知偏好：用户喜欢简短回答；已知事实：用户的项目使用Python。

与当前话题相关的历史记忆：
- [fact] 用户上周讨论了数据库迁移方案
- [preference] 用户偏好使用SQLite而非MySQL
```

---

## 7. API 端点

### Agent 级记忆 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/memory/agent/store` | 手动存储 Agent 记忆 |
| POST | `/api/memory/agent/search` | 搜索 Agent 记忆 |
| GET | `/api/memory/agent/{agent_id}/profile` | 获取 Agent 记忆画像 |
| POST | `/api/memory/agent/{agent_id}/consolidate` | 触发记忆整合 |
| GET | `/api/memory/agent/{agent_id}/stats` | 记忆统计 |
| DELETE | `/api/memory/agent/{agent_id}/{memory_id}` | 删除指定记忆 |

### 兼容旧 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/memory/store` | 存储 Session 级记忆（保留兼容） |
| GET | `/api/memory/search` | 搜索 Session 级记忆（保留兼容） |
| DELETE | `/api/memory/{memory_id}` | 删除记忆（保留兼容） |

---

## 8. 配置项

| 配置 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_MAX_TOKENS` | 1000 | 最大记忆 token 数（保留） |
| `MEMORY_VECTOR_DIMENSION` | 1536 | 向量维度（保留） |
| `MEMORY_MAX_RECENT_MESSAGES` | 20 | 工作记忆保留消息数 |
| `MEMORY_SUMMARY_THRESHOLD` | 30 | 触发摘要的消息数 |
| `MEMORY_SUMMARY_KEEP_RECENT` | 10 | 摘要时保留最近 N 轮 |
| `MEMORY_AUTO_EXTRACT` | True | 是否自动提取记忆 |
| `MEMORY_IMPORTANCE_THRESHOLD` | 0.3 | 召回最低重要性 |
| `MEMORY_DECAY_LAMBDA` | 0.05 | 衰减系数 |

---

## 9. 文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `app/services/session_working_memory.py` | 新建 | 统一的会话工作记忆 |
| `app/services/agent_memory_service.py` | 新建 | Agent 级长期记忆服务 |
| `app/models/agent_memory.py` | 新建 | Agent 记忆数据模型 |
| `app/api/chat.py` | 修改 | 接入记忆召回和自动提取 |
| `app/api/memory.py` | 修改 | 新增 Agent 级记忆 API |
| `app/main.py` | 修改 | 初始化新服务 |
| `app/config.py` | 修改 | 新增配置项 |
| `app/database/connection.py` | 修改 | 新增 agent_memories 表 |
| `app/database/repositories.py` | 修改 | 新增 AgentMemoryRepository |
| `app/services/vector_service.py` | 修改 | collection 改为 agent_{id} |
| `app/models/agent.py` | 修改 | 新增 enable_long_term_memory |
| `app/services/agent_service.py` | 修改 | 支持 enable_long_term_memory |
