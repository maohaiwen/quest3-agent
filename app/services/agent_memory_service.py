"""Agent Memory Service - Agent 级长期记忆服务

核心能力：
- 自动记忆提取（对话结束时批量提取）
- 语义搜索（ChromaDB, agent_{id} collection）
- 重要性分级 + 衰减
- 记忆整合（去重/合并/压缩）
"""
import json
import math
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.utils.timezone import beijing_now

from app.config import settings
from app.database.connection import DatabaseConnection
from app.database.repositories import AgentMemoryRepository
from app.models.agent_memory import (
    AgentMemoryItem, AgentMemoryProfile, AgentMemoryStats,
    MemoryType, MemorySource
)

logger = logging.getLogger(__name__)

MEMORY_EXTRACTION_PROMPT = """分析以下完整对话记录，提取需要长期记住的信息。

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
{{"content": "记忆内容（用第三人称或中性描述）", "type": "preference|fact|event", "importance": 0.0-1.0, "action": "add|update"}}
如果没有值得记住的信息，输出空数组 []"""


class AgentMemoryService:
    """Agent 级长期记忆服务"""

    PROFILE_CACHE_TTL = 300  # 5 minutes

    def __init__(self):
        self._vector_service = None
        self._profile_cache: Dict[str, tuple] = {}  # agent_id -> (profile, timestamp)

    def set_vector_service(self, vector_service):
        """设置向量服务实例"""
        self._vector_service = vector_service

    def _get_repo(self) -> AgentMemoryRepository:
        """获取新的 AgentMemoryRepository 实例

        注意：调用方必须在 finally 中调用 repo.db.disconnect() 关闭连接
        """
        db = DatabaseConnection(settings.DATABASE_URL)
        return AgentMemoryRepository(db)

    async def extract_and_store(
        self,
        agent_id: str,
        session_id: str,
        conversation_messages: List[Dict[str, Any]]
    ) -> int:
        """对话结束时，批量从整个对话中提取值得记住的信息

        Args:
            agent_id: Agent ID
            session_id: 来源 Session ID
            conversation_messages: 对话消息列表

        Returns:
            提取并存储的记忆数量
        """
        if not conversation_messages:
            return 0

        # 过滤出有意义的消息（至少有用户和助手各一条）
        meaningful = [m for m in conversation_messages if m.get("content")]
        if len(meaningful) < 2:
            return 0

        repo = self._get_repo()
        try:
            # 1. 获取已有记忆摘要（用于去重）
            existing_summary = await repo.get_memories_summary(agent_id, limit=20)

            # 2. 构建对话文本
            conversation_text = self._format_conversation(conversation_messages)

            # 3. 调用 LLM 提取记忆
            prompt = MEMORY_EXTRACTION_PROMPT.format(
                existing_memories_summary=existing_summary,
                conversation=conversation_text
            )

            extracted = await self._call_llm_for_extraction(prompt)
            if not extracted:
                logger.info(f"No memories extracted for agent {agent_id}")
                return 0

            # 4. 存储提取的记忆
            stored_count = 0
            for item in extracted:
                content = item.get("content", "").strip()
                memory_type = item.get("type", "fact")
                importance = float(item.get("importance", 0.5))
                action = item.get("action", "add")

                if not content:
                    continue

                # 验证 memory_type
                if memory_type not in ("preference", "fact", "event"):
                    memory_type = "fact"

                # 钳位重要性
                importance = max(0.0, min(1.0, importance))

                if action == "update":
                    # 尝试找到并更新类似记忆
                    similar = await repo.search_similar_content(agent_id, content[:50], limit=1)
                    if similar:
                        await repo.update(similar[0]["id"], content=content, importance=importance)
                        stored_count += 1
                        continue

                # 新增记忆
                memory_id = await repo.create(
                    agent_id=agent_id,
                    content=content,
                    memory_type=memory_type,
                    importance=importance,
                    session_id=session_id,
                    source="auto"
                )

                # 同时存入向量数据库
                if self._vector_service and self._vector_service.is_available():
                    try:
                        self._vector_service.add(
                            agent_id=agent_id,
                            content=content,
                            metadata={
                                "memory_id": memory_id,
                                "memory_type": memory_type,
                                "importance": importance,
                                "session_id": session_id,
                                "source": "auto"
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store memory in vector store: {e}")

                stored_count += 1

            logger.info(f"Extracted and stored {stored_count} memories for agent {agent_id}")
            # Invalidate profile cache since new memories were added
            self._profile_cache.pop(agent_id, None)
            return stored_count

        except Exception as e:
            logger.error(f"Error extracting memories for agent {agent_id}: {e}", exc_info=True)
            return 0
        finally:
            await repo.db.disconnect()

    async def recall(
        self,
        agent_id: str,
        query: str,
        n: int = 5,
        min_importance: float = None
    ) -> List[AgentMemoryItem]:
        """召回与当前查询相关的 agent 记忆

        Args:
            agent_id: Agent ID
            query: 查询文本
            n: 返回数量
            min_importance: 最低重要性阈值

        Returns:
            相关记忆列表
        """
        min_importance = min_importance or getattr(
            settings, 'MEMORY_IMPORTANCE_THRESHOLD', 0.3
        )

        # 优先从向量数据库语义搜索
        if self._vector_service and self._vector_service.is_available():
            try:
                results = self._vector_service.search(
                    agent_id=agent_id,
                    query=query,
                    n_results=n * 2  # 多取一些，再按重要性过滤
                )
                return await self._process_recall_results(agent_id, results, min_importance)
            except Exception as e:
                logger.warning(f"Vector search failed, falling back to DB: {e}")

        # Fallback: 从数据库获取高重要性记忆
        repo = self._get_repo()
        try:
            rows = await repo.get_high_importance(agent_id, min_importance=min_importance)
            return [self._row_to_item(row) for row in rows[:n]]
        finally:
            await repo.db.disconnect()

    async def get_agent_profile(self, agent_id: str) -> AgentMemoryProfile:
        """获取 agent 的记忆画像（高重要性偏好/事实），带 TTL 缓存

        Args:
            agent_id: Agent ID

        Returns:
            Agent 记忆画像
        """
        # Check cache
        cached = self._profile_cache.get(agent_id)
        if cached:
            profile, ts = cached
            if (beijing_now() - ts).total_seconds() < self.PROFILE_CACHE_TTL:
                return profile

        repo = self._get_repo()
        profile = None
        try:
            preferences = await repo.get_by_agent(
                agent_id, memory_type="preference", limit=10
            )
            facts = await repo.get_by_agent(
                agent_id, memory_type="fact", limit=10
            )
            total = await repo.count(agent_id)

            profile = AgentMemoryProfile(
                agent_id=agent_id,
                preferences=[p["content"] for p in preferences if p["importance"] >= 0.7],
                facts=[f["content"] for f in facts if f["importance"] >= 0.7],
                total_memories=total
            )
            return profile
        except Exception as e:
            logger.error(f"Error getting agent profile: {e}", exc_info=True)
            return AgentMemoryProfile(agent_id=agent_id)
        finally:
            await repo.db.disconnect()
            # Update cache on success
            if profile:
                self._profile_cache[agent_id] = (profile, beijing_now())
            await repo.db.disconnect()

    async def store_manual(
        self,
        agent_id: str,
        content: str,
        memory_type: str = "fact",
        importance: float = 0.5
    ) -> str:
        """手动存储记忆

        Args:
            agent_id: Agent ID
            content: 记忆内容
            memory_type: 记忆类型
            importance: 重要性

        Returns:
            记忆 ID
        """
        repo = self._get_repo()
        try:
            memory_id = await repo.create(
                agent_id=agent_id,
                content=content,
                memory_type=memory_type,
                importance=importance,
                source="manual"
            )

            # 同步到向量数据库
            if self._vector_service and self._vector_service.is_available():
                try:
                    self._vector_service.add(
                        agent_id=agent_id,
                        content=content,
                        metadata={
                            "memory_id": memory_id,
                            "memory_type": memory_type,
                            "importance": importance,
                            "source": "manual"
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to store in vector store: {e}")

            return memory_id
        except Exception as e:
            logger.error(f"Error storing manual memory: {e}", exc_info=True)
            raise
        finally:
            await repo.db.disconnect()
            # Invalidate profile cache
            self._profile_cache.pop(agent_id, None)

    async def consolidate(self, agent_id: str) -> Dict[str, int]:
        """记忆整合：删除低价值记忆，合并相似记忆

        Args:
            agent_id: Agent ID

        Returns:
            整合统计 {"deleted": n, "merged": n}
        """
        repo = self._get_repo()
        stats = {"deleted": 0, "merged": 0}

        try:
            # 1. 删除有效重要性过低的记忆
            all_memories = await repo.get_by_agent(agent_id, limit=1000)
            for mem in all_memories:
                eff = self._effective_importance(mem)
                if eff < 0.1:
                    await repo.delete(mem["id"])
                    # 从向量数据库删除
                    if self._vector_service and self._vector_service.is_available():
                        try:
                            self._vector_service.delete(agent_id, mem["id"])
                        except Exception:
                            pass
                    stats["deleted"] += 1

            # 2. 合并相似记忆（简单文本匹配）
            remaining = await repo.get_by_agent(agent_id, limit=500)
            seen_contents = set()
            for mem in remaining:
                # 简单去重：内容前50字符相同则视为相似
                key = mem["content"][:50]
                if key in seen_contents:
                    await repo.delete(mem["id"])
                    stats["merged"] += 1
                else:
                    seen_contents.add(key)

            logger.info(f"Consolidated memories for agent {agent_id}: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Error consolidating memories: {e}", exc_info=True)
            return stats
        finally:
            await repo.db.disconnect()

    async def get_stats(self, agent_id: str) -> AgentMemoryStats:
        """获取记忆统计"""
        repo = self._get_repo()
        try:
            all_memories = await repo.get_by_agent(agent_id, limit=1000)
            type_counts = {"preference": 0, "fact": 0, "event": 0, "summary": 0}
            total_importance = 0.0

            for mem in all_memories:
                mt = mem.get("memory_type", "fact")
                type_counts[mt] = type_counts.get(mt, 0) + 1
                total_importance += mem.get("importance", 0.5)

            total = len(all_memories)
            avg_importance = total_importance / total if total > 0 else 0.0

            return AgentMemoryStats(
                agent_id=agent_id,
                total_count=total,
                preference_count=type_counts["preference"],
                fact_count=type_counts["fact"],
                event_count=type_counts["event"],
                summary_count=type_counts["summary"],
                avg_importance=round(avg_importance, 3)
            )
        except Exception as e:
            logger.error(f"Error getting stats: {e}", exc_info=True)
            return AgentMemoryStats(agent_id=agent_id)
        finally:
            await repo.db.disconnect()

    # ---- 内部方法 ----

    # 按记忆类型区分的衰减系数（半衰期：preference ~140天, fact ~30天, event ~7天）
    DECAY_LAMBDA_BY_TYPE = {
        "preference": 0.005,  # 偏好几乎不衰减
        "fact": 0.023,        # 事实中等衰减
        "event": 0.099,       # 事件快速衰减
        "summary": 0.023,     # 摘要同 fact
    }
    DEFAULT_DECAY_LAMBDA = 0.023

    def _effective_importance(self, memory: dict) -> float:
        """计算记忆的有效重要性（按类型衰减 + 访问频率减缓衰减）"""
        importance = memory.get("importance", 0.5)
        last_accessed = memory.get("last_accessed_at")
        access_count = memory.get("access_count", 0)
        memory_type = memory.get("memory_type", "fact")

        # 按类型选择衰减系数
        decay_lambda = self.DECAY_LAMBDA_BY_TYPE.get(memory_type, self.DEFAULT_DECAY_LAMBDA)

        # 计算天数
        days = 0
        if last_accessed:
            if isinstance(last_accessed, datetime):
                days = (beijing_now() - last_accessed).days
            else:
                try:
                    days = (beijing_now() - datetime.fromisoformat(str(last_accessed))).days
                except Exception:
                    days = 0
        days = max(days, 0)

        # 基础衰减
        decay = math.exp(-decay_lambda * days)

        # 访问频率减缓衰减：每次访问使衰减系数降低（等效延长半衰期）
        # 公式：decay * (1 + 0.1 * min(access_count, 20))
        # 即访问10次时衰减速度减半，访问20次时衰减速度降至1/3
        access_slowdown = 1.0 + 0.1 * min(access_count, 20)

        effective_decay = math.exp(-decay_lambda * days / access_slowdown)

        return importance * effective_decay

    async def _process_recall_results(
        self,
        agent_id: str,
        vector_results: List[Dict],
        min_importance: float
    ) -> List[AgentMemoryItem]:
        """处理向量搜索结果，更新访问计数，按有效重要性排序"""
        repo = self._get_repo()
        items = []

        try:
            # 1. 收集所有 memory_id，批量查询 access_count 和 last_accessed_at
            memory_ids = []
            for result in vector_results:
                metadata = result.get("metadata", {})
                importance = metadata.get("importance", 0.5)
                if importance >= min_importance:
                    mid = metadata.get("memory_id", "")
                    if mid:
                        memory_ids.append(mid)

            # 一次批量查询所有需要的访问信息
            access_info: Dict[str, Dict] = {}
            if memory_ids:
                placeholders = ",".join("?" * len(memory_ids))
                rows = await repo.db.fetch_all(
                    f"SELECT id, access_count, last_accessed_at FROM agent_memories WHERE id IN ({placeholders})",
                    tuple(memory_ids)
                )
                for row in rows:
                    access_info[row["id"]] = {
                        "access_count": row.get("access_count", 0),
                        "last_accessed_at": row.get("last_accessed_at")
                    }

            # 2. 处理每条结果，计算有效重要性
            accessed_ids = []
            for result in vector_results:
                metadata = result.get("metadata", {})
                importance = metadata.get("importance", 0.5)

                if importance < min_importance:
                    continue

                memory_id = metadata.get("memory_id", "")
                info = access_info.get(memory_id, {})
                access_count = info.get("access_count", 0)
                last_accessed_at = info.get("last_accessed_at")

                # 计算有效重要性（含衰减）
                eff = self._effective_importance({
                    "importance": importance,
                    "access_count": access_count,
                    "last_accessed_at": last_accessed_at
                })

                # 用有效重要性过滤
                if eff < min_importance:
                    continue

                item = AgentMemoryItem(
                    id=memory_id,
                    agent_id=agent_id,
                    content=result.get("content", ""),
                    memory_type=metadata.get("memory_type", "fact"),
                    importance=importance,
                    access_count=access_count,
                    source=metadata.get("source", "auto"),
                    metadata=metadata,
                    last_accessed_at=datetime.fromisoformat(last_accessed_at) if last_accessed_at else None
                )

                items.append((eff, item))
                if memory_id:
                    accessed_ids.append(memory_id)

            # 3. 批量更新访问计数
            if accessed_ids:
                now = beijing_now().isoformat()
                placeholders = ",".join("?" * len(accessed_ids))
                try:
                    await repo.db.execute(
                        f"UPDATE agent_memories SET access_count = access_count + 1, last_accessed_at = ? WHERE id IN ({placeholders})",
                        (now, *accessed_ids)
                    )
                except Exception:
                    pass

            # 4. 按有效重要性排序
            items.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in items]
        finally:
            await repo.db.disconnect()

    def _row_to_item(self, row: dict) -> AgentMemoryItem:
        """将数据库行转为 AgentMemoryItem"""
        return AgentMemoryItem(
            id=row.get("id", ""),
            agent_id=row.get("agent_id", ""),
            session_id=row.get("session_id"),
            content=row.get("content", ""),
            memory_type=row.get("memory_type", "fact"),
            importance=row.get("importance", 0.5),
            access_count=row.get("access_count", 0),
            source=row.get("source", "auto"),
            metadata=row.get("metadata"),
            created_at=row.get("created_at"),
            last_accessed_at=row.get("last_accessed_at")
        )

    def _format_conversation(self, messages: List[Dict]) -> str:
        """将消息列表格式化为文本"""
        lines = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"用户: {content}")
            elif role == "assistant":
                lines.append(f"助手: {content}")
        return "\n".join(lines)

    async def _call_llm_for_extraction(self, prompt: str) -> List[Dict]:
        """调用 LLM 提取记忆

        Returns:
            提取的记忆列表，每项含 content, type, importance, action
        """
        try:
            from app.services.llm_service import llm_service

            if not llm_service.is_configured():
                logger.warning("LLM not configured, skipping memory extraction")
                return []

            messages = [{"role": "user", "content": prompt}]

            text = await llm_service.simple_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=2000,
            )

            if not text:
                return []

            text = text.strip()

            # 尝试解析 JSON
            # 处理可能的 markdown 代码块包裹
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])

            try:
                result = json.loads(text)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                # 尝试提取 JSON 数组
                start = text.find("[")
                end = text.rfind("]")
                if start >= 0 and end > start:
                    try:
                        result = json.loads(text[start:end+1])
                        if isinstance(result, list):
                            return result
                    except json.JSONDecodeError:
                        pass

            logger.warning(f"Failed to parse extraction result: {text[:200]}")
            return []

        except Exception as e:
            logger.error(f"Error calling LLM for extraction: {e}", exc_info=True)
            return []


# 全局实例
agent_memory_service = AgentMemoryService()
