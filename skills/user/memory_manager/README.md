# Memory Manager Skill

记忆管理器，为 Quest3 Agent 提供对话记忆的管理能力。

## 功能

- **view**: 查看会话记忆
- **search**: 搜索记忆内容
- **clear**: 清除会话记忆
- **stats**: 获取记忆统计信息

## 使用方法

通过 SkillExecutor 调用：

```python
from app.skills.executor import get_skill_executor

executor = get_skill_executor()

# 查看记忆
result = await executor.execute(
    "memory_manager",
    input_data={
        "action": "view",
        "session_id": "session_123",
        "params": {"limit": 10}
    }
)

# 搜索记忆
result = await executor.execute(
    "memory_manager",
    input_data={
        "action": "search",
        "session_id": "session_123",
        "params": {"keyword": "Python"}
    }
)

# 清除记忆
result = await executor.execute(
    "memory_manager",
    input_data={
        "action": "clear",
        "session_id": "session_123",
        "params": {"count": 5}  # 保留最近5条，0表示全部清除
    }
)

# 获取统计
result = await executor.execute(
    "memory_manager",
    input_data={
        "action": "stats",
        "session_id": "session_123"
    }
)
```

## 文件结构

```
memory_manager/
├── skill.md    # Skill描述文件
├── main.py     # 入口脚本
└── README.md   # 本文档
