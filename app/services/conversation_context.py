"""对话上下文管理器 - 处理多轮对话中的 reasoning_content 过滤"""
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class ConversationContext:
    """
    对话上下文管理器
    负责管理多轮对话的上下文，正确处理 reasoning_content 字段
    """

    def __init__(self):
        """初始化对话上下文管理器"""
        self.contexts: Dict[str, List[Dict[str, Any]]] = {}

    def get_context(self, session_id: str, model_version: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取对话上下文

        Args:
            session_id: 会话 ID
            model_version: 模型版本（用于确定是否需要过滤 reasoning_content）

        Returns:
            过滤后的上下文消息列表
        """
        if session_id not in self.contexts:
            self.contexts[session_id] = []

        context = self.contexts[session_id]

        # 过滤 reasoning_content
        return self._filter_thinking_content(context, model_version)

    def add_message(self, session_id: str, role: str, content: str, reasoning_content: Optional[str] = None):
        """
        添加消息到上下文

        Args:
            session_id: 会话 ID
            role: 消息角色 (user/assistant/system)
            content: 消息内容
            reasoning_content: 思考内容（可选）
        """
        if session_id not in self.contexts:
            self.contexts[session_id] = []

        message = {
            "role": role,
            "content": content,
        }

        # 如果有模型支持 reasoning_content，则保存
        if reasoning_content is not None:
            message["reasoning_content"] = reasoning_content

        self.contexts[session_id].append(message)
        logger.debug(f"Added message to session {session_id}: role={role}, content_length={len(content)}")

    def _filter_thinking_content(
        self,
        messages: List[Dict[str, Any]],
        model_version: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        过滤消息中的 reasoning_content

        Args:
            messages: 原始消息列表
            model_version: 模型版本

        Returns:
            过滤后的消息列表
        """
        filtered = []

        for msg in messages:
            # 创建消息副本
            filtered_msg = {
                "role": msg["role"],
                "content": msg["content"]
            }

            # 根据 Volcengine SDK 文档：
            # - 如果模型支持 reasoning_content，则保留该字段
            # - 如果不支持，则过滤掉该字段
            # - 对于响应消息，通常不需要包含 reasoning_content

            # 默认不过滤 reasoning_content（由 SDK 处理）
            if "reasoning_content" in msg and model_version:
                filtered_msg["reasoning_content"] = msg["reasoning_content"]

            filtered.append(filtered_msg)

        return filtered

    def clear(self, session_id: str):
        """
        清空指定会话的上下文

        Args:
            session_id: 会话 ID
        """
        if session_id in self.contexts:
            self.contexts[session_id] = []
            logger.info(f"Cleared context for session {session_id}")

    def load_from_db(self, session_id: str, db_messages: List[Dict[str, Any]]):
        """
        从数据库加载对话历史

        Args:
            session_id: 会话 ID
            db_messages: 数据库消息列表
        """
        self.contexts[session_id] = []
        for msg in db_messages:
            self.add_message(
                session_id,
                msg.get("role", "user"),
                msg.get("content", ""),
                msg.get("reasoning_content")
            )
        logger.info(f"Loaded {len(db_messages)} messages from DB for session {session_id}")


# 全局实例
_conversation_context_instance: Optional[ConversationContext] = None


def get_conversation_context() -> ConversationContext:
    """获取对话上下文管理器全局实例"""
    global _conversation_context_instance
    if _conversation_context_instance is None:
        _conversation_context_instance = ConversationContext()
    return _conversation_context_instance
