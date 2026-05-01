"""
记忆管理器 Skill

提供查看、搜索、清除和管理对话记忆的功能
"""
from typing import Any, Dict, List, Optional
from datetime import datetime

# 注意：实际项目中应该从 app.services.memory_service 导入
# 这里为了技能独立性，使用内存模拟


class MockMemory:
    """模拟记忆服务（实际项目中替换为真实服务）"""

    def __init__(self):
        self._sessions: Dict[str, List[Dict]] = {}

    def get_session(self, session_id: str) -> List[Dict]:
        if session_id not in self._sessions:
            # 初始化一些测试数据
            self._sessions[session_id] = [
                {"role": "user", "content": "你好，请介绍一下你自己", "timestamp": "2024-01-15T10:00:00"},
                {"role": "assistant", "content": "我是Quest3 Agent，一个AI智能助手", "timestamp": "2024-01-15T10:00:01"},
                {"role": "user", "content": "你能做什么？", "timestamp": "2024-01-15T10:01:00"},
                {"role": "assistant", "content": "我可以进行对话、记忆管理、代码审查等多种任务", "timestamp": "2024-01-15T10:01:01"},
                {"role": "user", "content": "帮我写一个Python函数", "timestamp": "2024-01-15T10:02:00"},
                {"role": "assistant", "content": "当然可以，请告诉我你需要什么功能的函数？", "timestamp": "2024-01-15T10:02:01"},
                {"role": "user", "content": "计算斐波那契数列", "timestamp": "2024-01-15T10:03:00"},
                {"role": "assistant", "content": "好的，这是一个计算斐波那契数列的函数...", "timestamp": "2024-01-15T10:03:01"},
                {"role": "user", "content": "还有其他方法吗？", "timestamp": "2024-01-15T10:04:00"},
                {"role": "assistant", "content": "是的，还有矩阵快速幂和公式法等方法", "timestamp": "2024-01-15T10:04:01"},
            ]
        return self._sessions[session_id]

    def clear_session(self, session_id: str, keep_count: int = 0) -> int:
        if session_id in self._sessions:
            current = self._sessions[session_id]
            if keep_count >= len(current):
                return 0
            cleared = len(current) - keep_count
            self._sessions[session_id] = current[-keep_count:] if keep_count > 0 else []
            return cleared
        return 0

    def set_session(self, session_id: str, messages: List[Dict]) -> None:
        self._sessions[session_id] = messages


# 全局模拟记忆实例
_mock_memory = MockMemory()


def execute(context) -> Dict[str, Any]:
    """
    Skill 入口函数

    Args:
        context: 执行上下文，包含：
            - input_data: 输入数据，包含 action, session_id, params
            - config: 配置
            - state: 状态（可修改）

    Returns:
        执行结果
    """
    input_data = context.input_data or {}
    session_id = input_data.get("session_id", "default_session")

    action = input_data.get("action", "")

    # 根据 action 执行不同操作
    if action == "view":
        return _handle_view(session_id, input_data.get("params", {}))
    elif action == "search":
        return _handle_search(session_id, input_data.get("params", {}))
    elif action == "clear":
        return _handle_clear(session_id, input_data.get("params", {}))
    elif action == "stats":
        return _handle_stats(session_id)
    else:
        return {
            "status": "error",
            "error": f"Unknown action: {action}",
            "action": action,
            "available_actions": ["view", "search", "clear", "stats"]
        }


def _handle_view(session_id: str, params: Dict) -> Dict[str, Any]:
    """处理 view 操作"""
    limit = params.get("limit", 10)

    messages = _mock_memory.get_session(session_id)
    total = len(messages)

    # 返回最近 limit 条
    view_messages = messages[-limit:] if limit > 0 else messages

    return {
        "status": "success",
        "action": "view",
        "data": {
            "messages": view_messages,
            "count": len(view_messages),
            "total": total,
            "showing_last": limit if limit > 0 else total
        }
    }


def _handle_search(session_id: str, params: Dict) -> Dict[str, Any]:
    """处理 search 操作"""
    keyword = params.get("keyword", "").lower()

    if not keyword:
        return {
            "status": "error",
            "action": "search",
            "error": "Keyword is required for search"
        }

    messages = _mock_memory.get_session(session_id)
    results = []

    for idx, msg in enumerate(messages):
        if keyword in msg.get("content", "").lower():
            results.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
                "index": idx,
                "timestamp": msg.get("timestamp")
            })

    return {
        "status": "success",
        "action": "search",
        "data": {
            "results": results,
            "count": len(results),
            "keyword": keyword
        }
    }


def _handle_clear(session_id: str, params: Dict) -> Dict[str, Any]:
    """处理 clear 操作"""
    count = params.get("count", 0)  # 0 表示全部清除

    if count == 0:
        # 全部清除
        messages_before = len(_mock_memory.get_session(session_id))
        _mock_memory.clear_session(session_id, keep_count=0)
        return {
            "status": "success",
            "action": "clear",
            "data": {
                "cleared_count": messages_before,
                "remaining_count": 0
            }
        }
    else:
        # 保留最近 count 条
        cleared = _mock_memory.clear_session(session_id, keep_count=count)
        remaining = len(_mock_memory.get_session(session_id))
        return {
            "status": "success",
            "action": "clear",
            "data": {
                "cleared_count": cleared,
                "remaining_count": remaining
            }
        }


def _handle_stats(session_id: str) -> Dict[str, Any]:
    """处理 stats 操作"""
    messages = _mock_memory.get_session(session_id)

    user_count = sum(1 for m in messages if m.get("role") == "user")
    assistant_count = sum(1 for m in messages if m.get("role") == "assistant")

    timestamps = [m.get("timestamp") for m in messages if m.get("timestamp")]

    return {
        "status": "success",
        "action": "stats",
        "data": {
            "message_count": len(messages),
            "user_message_count": user_count,
            "assistant_message_count": assistant_count,
            "oldest_message": min(timestamps) if timestamps else None,
            "newest_message": max(timestamps) if timestamps else None
        }
    }
