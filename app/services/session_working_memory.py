"""Session Working Memory - 统一的会话工作记忆

合并原有 MemoryService + ConversationContext，消除冗余。
- 内存缓存当前对话上下文
- 保留 reasoning_content 用于深度思考模型
- 支持过滤后输出给 LLM
- 支持对话摘要（消息过多时自动压缩）
"""
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from app.config import settings
from app.models.chat import MessageRole

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """请将以下对话历史压缩为简洁的摘要，保留：
1. 讨论的主要话题和结论
2. 用户的明确偏好或要求
3. 未解决的待办事项

对话历史：
{conversation}

输出格式：简洁的段落摘要，不超过200字。"""


@dataclass
class WorkingContext:
    """单个 session 的工作上下文"""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    summary: Optional[str] = None
    recalled_memories: List[Dict[str, Any]] = field(default_factory=list)


class SessionWorkingMemory:
    """统一的会话工作记忆 - 合并 MemoryService + ConversationContext"""

    def __init__(self, max_recent_messages: int = None):
        """初始化

        Args:
            max_recent_messages: 保留的最大最近消息数，默认从配置读取
        """
        self.max_recent_messages = max_recent_messages or getattr(
            settings, 'MEMORY_MAX_RECENT_MESSAGES', 20
        )
        self._summary_threshold = getattr(settings, 'MEMORY_SUMMARY_THRESHOLD', 30)
        self._summary_keep_recent = getattr(settings, 'MEMORY_SUMMARY_KEEP_RECENT', 10)
        self._sessions: Dict[str, WorkingContext] = {}

    def _get_or_create(self, session_id: str) -> WorkingContext:
        """获取或创建 session 上下文"""
        if session_id not in self._sessions:
            self._sessions[session_id] = WorkingContext()
        return self._sessions[session_id]

    def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        reasoning_content: Optional[str] = None
    ) -> None:
        """添加消息到会话工作记忆

        Args:
            session_id: Session ID
            role: 消息角色
            content: 消息内容
            reasoning_content: 思考内容（可选，深度思考模型使用）
        """
        ctx = self._get_or_create(session_id)
        message: Dict[str, Any] = {
            "role": role.value if isinstance(role, MessageRole) else role,
            "content": content,
        }
        if reasoning_content is not None:
            message["reasoning_content"] = reasoning_content
        ctx.messages.append(message)
        logger.debug(
            f"Added message to session {session_id}: "
            f"role={message['role']}, content_length={len(content)}"
        )

    def add_user_message(self, session_id: str, content: str) -> None:
        """添加用户消息"""
        self.add_message(session_id, MessageRole.USER, content)

    def add_assistant_message(
        self,
        session_id: str,
        content: str,
        reasoning_content: Optional[str] = None
    ) -> None:
        """添加助手消息"""
        self.add_message(session_id, MessageRole.ASSISTANT, content, reasoning_content)

    def get_recent_messages(self, session_id: str, n: Optional[int] = None) -> List[dict]:
        """获取最近 N 条消息（原始格式，含 reasoning_content）

        Args:
            session_id: Session ID
            n: 获取的消息数，默认取 max_recent_messages

        Returns:
            消息列表
        """
        ctx = self._sessions.get(session_id)
        if not ctx:
            return []
        limit = n or self.max_recent_messages
        return ctx.messages[-limit:] if limit > 0 else ctx.messages.copy()

    def get_conversation_history(self, session_id: str, limit: Optional[int] = None) -> List[dict]:
        """获取对话历史（兼容旧 MemoryService 接口）

        如果存在摘要，会将摘要作为 system 消息插入到消息列表头部。

        Args:
            session_id: Session ID
            limit: 可选的消息数限制

        Returns:
            消息列表
        """
        ctx = self._sessions.get(session_id)
        if not ctx:
            return []

        messages = ctx.messages[-limit:] if limit else ctx.messages.copy()

        # 如果有摘要，在头部插入
        if ctx.summary:
            messages = [{"role": "system", "content": f"【对话历史摘要】\n{ctx.summary}"}] + messages

        return messages

    def get_context_for_llm(
        self,
        session_id: str,
        model_version: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取给 LLM 使用的上下文（过滤 reasoning_content）

        替代原有 ConversationContext.get_context() 的功能。

        Args:
            session_id: Session ID
            model_version: 模型版本（用于决定是否保留 reasoning_content）

        Returns:
            过滤后的消息列表
        """
        ctx = self._sessions.get(session_id)
        if not ctx:
            return []

        filtered = []
        for msg in ctx.messages:
            filtered_msg = {
                "role": msg["role"],
                "content": msg["content"]
            }
            # 只有指定了 model_version 且消息含 reasoning_content 时才保留
            if "reasoning_content" in msg and model_version:
                filtered_msg["reasoning_content"] = msg["reasoning_content"]
            filtered.append(filtered_msg)

        return filtered

    def get_all_messages(self, session_id: str) -> List[dict]:
        """获取会话全部消息（含 reasoning_content，不截断）

        用于对话结束时批量提取记忆。

        Args:
            session_id: Session ID

        Returns:
            完整消息列表
        """
        ctx = self._sessions.get(session_id)
        if not ctx:
            return []
        return ctx.messages.copy()

    def message_count(self, session_id: str) -> int:
        """获取消息数量"""
        ctx = self._sessions.get(session_id)
        return len(ctx.messages) if ctx else 0

    def get_summary(self, session_id: str) -> Optional[str]:
        """获取会话摘要"""
        ctx = self._sessions.get(session_id)
        return ctx.summary if ctx else None

    async def maybe_summarize(self, session_id: str, agent_model: Optional[str] = None) -> bool:
        """检查是否需要摘要，如果需要则生成

        使用 agent 配置的同一模型做摘要，保证质量。

        Args:
            session_id: Session ID
            agent_model: Agent 使用的模型名称

        Returns:
            True if summary was generated
        """
        ctx = self._sessions.get(session_id)
        if not ctx or len(ctx.messages) <= self._summary_threshold:
            return False

        try:
            old_messages = ctx.messages[:-self._summary_keep_recent]
            conversation_text = self._format_messages_for_summary(old_messages)

            summary = await self._generate_summary(conversation_text, agent_model)
            if summary:
                # 保留已有摘要 + 新摘要
                if ctx.summary:
                    ctx.summary = ctx.summary + "\n\n" + summary
                else:
                    ctx.summary = summary

                # 截断旧消息，保留最近的
                ctx.messages = ctx.messages[-self._summary_keep_recent:]
                logger.info(
                    f"Summarized session {session_id}: "
                    f"summary_len={len(summary)}, remaining_messages={len(ctx.messages)}"
                )
                return True

        except Exception as e:
            logger.error(f"Error generating summary for session {session_id}: {e}", exc_info=True)

        return False

    async def _generate_summary(self, conversation_text: str, model: Optional[str] = None) -> Optional[str]:
        """使用 LLM 生成对话摘要

        Args:
            conversation_text: 格式化后的对话文本
            model: 使用的模型

        Returns:
            摘要文本
        """
        try:
            from app.services.llm_service import llm_service

            if not llm_service.volc_client:
                return None

            prompt = SUMMARY_PROMPT.format(conversation=conversation_text)
            messages = [{"role": "user", "content": prompt}]

            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: llm_service.volc_client.chat.completions.create(
                    model=model or llm_service.model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=500,
                    stream=False
                )
            )

            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"Error calling LLM for summary: {e}", exc_info=True)

        return None

    def _format_messages_for_summary(self, messages: List[Dict]) -> str:
        """将消息列表格式化为摘要用的文本"""
        lines = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"助手: {content}")
        return "\n".join(lines)

    def load_from_db(self, session_id: str, db_messages: List[Dict]) -> None:
        """从数据库加载消息到工作记忆

        Args:
            session_id: Session ID
            db_messages: 数据库消息列表，每项含 role, content, 可选 reasoning_content
        """
        ctx = self._get_or_create(session_id)
        ctx.messages = []
        for msg in db_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            reasoning_content = msg.get("reasoning_content")
            self.add_message(session_id, MessageRole(role), content, reasoning_content)
        logger.info(
            f"Loaded {len(db_messages)} messages from DB for session {session_id}"
        )

    def clear_session(self, session_id: str) -> None:
        """清空指定会话的工作记忆"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Cleared working memory for session {session_id}")

    @property
    def session_count(self) -> int:
        """当前活跃 session 数"""
        return len(self._sessions)


# 全局实例
session_working_memory = SessionWorkingMemory()
