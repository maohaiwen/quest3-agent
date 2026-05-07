"""
Skill 触发机制

实现多种触发策略：关键词、意图匹配、正则表达式
"""
import asyncio
import logging
import re
import uuid
from datetime import datetime
from app.utils.timezone import beijing_now
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.models.skill import Skill
from app.skills.registry import SkillRegistry, get_skill_registry

logger = logging.getLogger(__name__)


# ============================================
# 触发类型
# ============================================

class TriggerType(str, Enum):
    """触发类型"""
    KEYWORD = "keyword"          # 关键词匹配
    INTENT = "intent"            # 意图匹配（LLM）
    REGEX = "regex"              # 正则表达式
    ALWAYS = "always"            # 总是触发
    MANUAL = "manual"            # 仅手动触发


class KeywordTriggerConfig(BaseModel):
    """关键词触发配置"""
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    case_sensitive: bool = Field(default=False, description="大小写敏感")
    match_all: bool = Field(default=False, description="需要匹配所有关键词")


class RegexTriggerConfig(BaseModel):
    """正则触发配置"""
    pattern: str = Field(..., description="正则表达式")
    flags: List[str] = Field(default_factory=list, description="正则 flags")


class IntentTriggerConfig(BaseModel):
    """意图触发配置"""
    intent_description: str = Field(..., description="意图描述")
    confidence_threshold: float = Field(default=0.7, description="置信度阈值")


class SkillTrigger(BaseModel):
    """Skill 触发规则"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    skill_id: str = Field(..., description="关联的 Skill ID")
    skill_name: Optional[str] = Field(default=None, description="Skill 名称（缓存）")
    trigger_type: TriggerType = Field(..., description="触发类型")
    config: Dict[str, Any] = Field(default_factory=dict, description="触发配置")
    priority: int = Field(default=0, description="优先级（数字越大越优先）")
    enabled: bool = Field(default=True, description="是否启用")
    created_at: datetime = Field(default_factory=beijing_now)


# ============================================
# Skill 触发管理器
# ============================================

class SkillTriggerManager:
    """Skill 触发管理器"""

    def __init__(self, skill_registry: SkillRegistry = None):
        self.registry = skill_registry or get_skill_registry()
        self._triggers: Dict[str, SkillTrigger] = {}  # trigger_id -> trigger
        self._skill_triggers: Dict[str, List[str]] = {}  # skill_id -> [trigger_ids]
        self._name_to_id: Dict[str, str] = {}  # skill_name -> skill_id

        # 确保 registry 初始化
        if not self.registry._loaded:
            self.registry.initialize()

        # 从已加载的 skill 中解析触发配置
        self._load_triggers_from_skills()

    def _load_triggers_from_skills(self) -> None:
        """从已加载的 Skill 中解析触发配置"""
        skills = self.registry.get_all_skills()

        for skill in skills.values():
            self._load_triggers_from_skill(skill)

    def _load_triggers_from_skill(self, skill: Skill) -> None:
        """从单个 Skill 解析触发配置"""
        # 尝试从 skill_content 中解析 frontmatter
        # 这里简化处理，我们可以通过 skill 的字段来获取
        # 实际上，trigger 配置应该在 skill.md 的 frontmatter 中

        # 尝试从 skill 的 tags 或 description 中生成默认触发
        # 如果有 tags，用 tags 作为关键词
        if skill.tags:
            trigger = SkillTrigger(
                skill_id=skill.id,
                skill_name=skill.name,
                trigger_type=TriggerType.KEYWORD,
                config=KeywordTriggerConfig(
                    keywords=skill.tags + [skill.name],
                    case_sensitive=False,
                    match_all=False,
                ).dict(),
                priority=1,
                enabled=True,
            )
            self.add_trigger(trigger)

        # 缓存 name -> id 映射
        self._name_to_id[skill.name] = skill.id

    def add_trigger(self, trigger: SkillTrigger) -> None:
        """添加触发规则"""
        self._triggers[trigger.id] = trigger

        if trigger.skill_id not in self._skill_triggers:
            self._skill_triggers[trigger.skill_id] = []

        if trigger.id not in self._skill_triggers[trigger.skill_id]:
            self._skill_triggers[trigger.skill_id].append(trigger.id)

        logger.debug(f"Added trigger: {trigger.id} for skill {trigger.skill_id}")

    def remove_trigger(self, trigger_id: str) -> bool:
        """移除触发规则"""
        trigger = self._triggers.pop(trigger_id, None)
        if trigger and trigger.skill_id in self._skill_triggers:
            if trigger_id in self._skill_triggers[trigger.skill_id]:
                self._skill_triggers[trigger.skill_id].remove(trigger_id)
            logger.debug(f"Removed trigger: {trigger_id}")
            return True
        return False

    def get_triggers_for_skill(self, skill_id: str) -> List[SkillTrigger]:
        """获取 skill 的所有触发规则"""
        trigger_ids = self._skill_triggers.get(skill_id, [])
        return [self._triggers[tid] for tid in trigger_ids if tid in self._triggers]

    def get_triggers_for_skill_by_name(self, skill_name: str) -> List[SkillTrigger]:
        """通过 skill name 获取触发规则"""
        skill_id = self._name_to_id.get(skill_name)
        if skill_id:
            return self.get_triggers_for_skill(skill_id)
        return []

    def get_all_triggers(self) -> List[SkillTrigger]:
        """获取所有触发规则"""
        return list(self._triggers.values())

    async def find_matching_skills(
        self,
        message: str,
        session_id: str = None,
        limit: int = 5,
    ) -> List[Tuple[Skill, float, SkillTrigger]]:
        """
        查找匹配的 Skills

        Args:
            message: 用户消息
            session_id: 会话 ID
            limit: 返回结果数量限制

        Returns:
            List of (Skill, confidence, Trigger) tuples, sorted by confidence and priority
        """
        matches = []

        for trigger in self._triggers.values():
            if not trigger.enabled:
                continue

            confidence = await self._check_trigger(trigger, message)
            if confidence > 0:
                skill = self._get_skill_for_trigger(trigger)
                if skill and skill.enabled:
                    matches.append((skill, confidence, trigger))

        # 排序：先按优先级，再按置信度
        matches.sort(key=lambda x: (-x[2].priority, -x[1]))

        # 去重（保留最高置信度的）
        seen = set()
        unique_matches = []
        for skill, conf, trigger in matches:
            if skill.id not in seen:
                seen.add(skill.id)
                unique_matches.append((skill, conf, trigger))
                if len(unique_matches) >= limit:
                    break

        return unique_matches

    def _get_skill_for_trigger(self, trigger: SkillTrigger) -> Optional[Skill]:
        """获取 trigger 关联的 skill"""
        # 先通过 skill_id 查找
        skills = self.registry.get_all_skills()
        for skill in skills.values():
            if skill.id == trigger.skill_id:
                return skill

        # 再通过 skill_name 查找
        if trigger.skill_name:
            skill = self.registry.get_skill(trigger.skill_name)
            if skill:
                return skill

        return None

    async def _check_trigger(
        self,
        trigger: SkillTrigger,
        message: str,
    ) -> float:
        """检查触发是否匹配，返回置信度 (0-1)"""
        if trigger.trigger_type == TriggerType.KEYWORD:
            return await self._check_keyword_trigger(trigger, message)
        elif trigger.trigger_type == TriggerType.REGEX:
            return await self._check_regex_trigger(trigger, message)
        elif trigger.trigger_type == TriggerType.INTENT:
            return await self._check_intent_trigger(trigger, message)
        elif trigger.trigger_type == TriggerType.ALWAYS:
            return 1.0
        elif trigger.trigger_type == TriggerType.MANUAL:
            return 0.0
        else:
            return 0.0

    async def _check_keyword_trigger(
        self,
        trigger: SkillTrigger,
        message: str,
    ) -> float:
        """关键词匹配"""
        try:
            config = KeywordTriggerConfig(**trigger.config)
        except Exception:
            return 0.0

        message_lower = message.lower() if not config.case_sensitive else message

        matched_count = 0
        for keyword in config.keywords:
            kw = keyword.lower() if not config.case_sensitive else keyword
            if kw in message_lower:
                matched_count += 1

        if config.match_all:
            return 1.0 if matched_count == len(config.keywords) else 0.0
        else:
            return matched_count / len(config.keywords) if config.keywords else 0.0

    async def _check_regex_trigger(
        self,
        trigger: SkillTrigger,
        message: str,
    ) -> float:
        """正则匹配"""
        try:
            config = RegexTriggerConfig(**trigger.config)
        except Exception:
            return 0.0

        flags = 0
        for flag_str in config.flags:
            flag_name = flag_str.upper()
            if hasattr(re, flag_name):
                flags |= getattr(re, flag_name)

        try:
            if re.search(config.pattern, message, flags):
                return 1.0
        except re.error:
            logger.warning(f"Invalid regex pattern: {config.pattern}")

        return 0.0

    async def _check_intent_trigger(
        self,
        trigger: SkillTrigger,
        message: str,
    ) -> float:
        """
        意图匹配（使用 LLM）

        注意：此功能需要集成 LLM 服务才能工作
        目前返回 0，作为占位实现
        """
        try:
            config = IntentTriggerConfig(**trigger.config)
        except Exception:
            return 0.0

        # TODO: 集成 LLM 服务来判断意图匹配度
        # 这里是一个占位实现
        # 可以使用 LLM 来分析消息是否匹配意图描述

        # 暂时返回 0，需要实现 LLM 集成
        logger.debug(
            f"Intent trigger not implemented yet: {config.intent_description}"
        )
        return 0.0

    def add_keyword_trigger(
        self,
        skill_name: str,
        keywords: List[str],
        priority: int = 10,
        case_sensitive: bool = False,
        match_all: bool = False,
    ) -> SkillTrigger:
        """
        为 Skill 添加关键词触发

        这是一个便捷方法
        """
        skill = self.registry.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill not found: {skill_name}")

        config = KeywordTriggerConfig(
            keywords=keywords,
            case_sensitive=case_sensitive,
            match_all=match_all,
        )

        trigger = SkillTrigger(
            skill_id=skill.id,
            skill_name=skill_name,
            trigger_type=TriggerType.KEYWORD,
            config=config.dict(),
            priority=priority,
            enabled=True,
        )

        self.add_trigger(trigger)
        return trigger

    def add_regex_trigger(
        self,
        skill_name: str,
        pattern: str,
        flags: List[str] = None,
        priority: int = 10,
    ) -> SkillTrigger:
        """
        为 Skill 添加正则触发

        这是一个便捷方法
        """
        skill = self.registry.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill not found: {skill_name}")

        config = RegexTriggerConfig(
            pattern=pattern,
            flags=flags or [],
        )

        trigger = SkillTrigger(
            skill_id=skill.id,
            skill_name=skill_name,
            trigger_type=TriggerType.REGEX,
            config=config.dict(),
            priority=priority,
            enabled=True,
        )

        self.add_trigger(trigger)
        return trigger

    def reload_skills(self) -> None:
        """重新加载技能并更新触发器"""
        self.registry.reload()
        self._triggers.clear()
        self._skill_triggers.clear()
        self._load_triggers_from_skills()


# ============================================
# 全局实例
# ============================================

_trigger_manager: Optional[SkillTriggerManager] = None


def get_trigger_manager() -> SkillTriggerManager:
    """获取或创建全局 SkillTriggerManager"""
    global _trigger_manager
    if _trigger_manager is None:
        _trigger_manager = SkillTriggerManager()
    return _trigger_manager
