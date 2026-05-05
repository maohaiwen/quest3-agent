"""Agent Memory models - Agent 级长期记忆数据模型"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class MemoryType(str, Enum):
    """记忆类型"""
    PREFERENCE = "preference"  # 用户偏好/习惯
    FACT = "fact"              # 重要事实
    EVENT = "event"            # 值得记住的事件
    SUMMARY = "summary"        # 对话摘要


class MemorySource(str, Enum):
    """记忆来源"""
    AUTO = "auto"      # 自动提取
    MANUAL = "manual"  # 手动存储


class AgentMemoryCreate(BaseModel):
    """Agent 记忆创建请求"""
    agent_id: str = Field(..., description="Agent ID")
    content: str = Field(..., description="记忆内容")
    memory_type: MemoryType = Field(default=MemoryType.FACT, description="记忆类型")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要性 0.0-1.0")
    session_id: Optional[str] = Field(default=None, description="来源 Session ID")
    source: MemorySource = Field(default=MemorySource.MANUAL, description="来源类型")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="额外元数据")


class AgentMemoryItem(BaseModel):
    """Agent 记忆条目"""
    id: str = Field(..., description="记忆 ID")
    agent_id: str = Field(..., description="Agent ID")
    session_id: Optional[str] = Field(default=None, description="来源 Session ID")
    content: str = Field(..., description="记忆内容")
    memory_type: MemoryType = Field(..., description="记忆类型")
    importance: float = Field(default=0.5, description="重要性")
    access_count: int = Field(default=0, description="被召回次数")
    source: MemorySource = Field(default=MemorySource.AUTO, description="来源类型")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="元数据")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    last_accessed_at: Optional[datetime] = Field(default=None, description="最后访问时间")


class AgentMemoryProfile(BaseModel):
    """Agent 记忆画像 - 高重要性偏好和事实的汇总"""
    agent_id: str = Field(..., description="Agent ID")
    preferences: List[str] = Field(default_factory=list, description="偏好列表")
    facts: List[str] = Field(default_factory=list, description="重要事实列表")
    total_memories: int = Field(default=0, description="总记忆数")

    def to_prompt_text(self) -> str:
        """转换为可注入 system prompt 的文本"""
        parts = []
        if self.preferences:
            parts.append("已知偏好：" + "；".join(self.preferences))
        if self.facts:
            parts.append("已知事实：" + "；".join(self.facts))
        if not parts:
            return ""
        return "关于对话对象的记忆：" + "。".join(parts)


class AgentMemorySearchRequest(BaseModel):
    """Agent 记忆搜索请求"""
    agent_id: str = Field(..., description="Agent ID")
    query: str = Field(..., description="搜索查询")
    n: int = Field(default=5, description="返回数量")
    min_importance: float = Field(default=0.3, description="最低重要性")


class AgentMemorySearchResponse(BaseModel):
    """Agent 记忆搜索响应"""
    results: List[AgentMemoryItem] = Field(default_factory=list)
    query: str = Field(..., description="搜索查询")
    count: int = Field(default=0, description="结果数")


class AgentMemoryStats(BaseModel):
    """Agent 记忆统计"""
    agent_id: str = Field(..., description="Agent ID")
    total_count: int = Field(default=0, description="总记忆数")
    preference_count: int = Field(default=0, description="偏好数")
    fact_count: int = Field(default=0, description="事实数")
    event_count: int = Field(default=0, description="事件数")
    summary_count: int = Field(default=0, description="摘要数")
    avg_importance: float = Field(default=0.0, description="平均重要性")
