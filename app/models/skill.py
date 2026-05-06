"""Skill models for the agent system"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class SkillSource(str, Enum):
    """Skill source type"""
    BUILTIN = "builtin"  # 内置 Skill
    USER = "user"        # 用户自定义
    GITHUB = "github"    # 从 GitHub 导入
    GIST = "gist"        # 从 Gist 导入
    URL = "url"          # 从 URL 导入


class SkillConfig(BaseModel):
    """Skill configuration schema"""
    type: str = Field(default="object", description="JSON Schema type")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Schema properties")
    required: List[str] = Field(default_factory=list, description="Required fields")


class SkillMetadata(BaseModel):
    """Skill metadata from frontmatter"""
    name: str = Field(..., description="Skill unique identifier")
    version: str = Field(default="1.0.0", description="Skill version")
    description: str = Field(default="", description="Skill description")
    author: Optional[str] = Field(default=None, description="Author name")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    requirements: List[str] = Field(default_factory=list, description="Python requirements")
    tools: List[str] = Field(default_factory=list, description="Required tools")
    config_schema: Optional[SkillConfig] = Field(default=None, description="Config schema")
    entrypoint: Optional[str] = Field(default=None, description="Entrypoint script file (e.g. main.py)")
    files: List[str] = Field(default_factory=list, description="List of skill files (excluding skill.md)")


class Skill(BaseModel):
    """Skill model"""
    id: str = Field(..., description="Skill ID")
    name: str = Field(..., description="Skill name")
    description: str = Field(default="", description="Skill description")
    version: str = Field(default="1.0.0", description="Skill version")
    author: Optional[str] = Field(default=None, description="Author name")
    tags: List[str] = Field(default_factory=list, description="Tags")
    source: SkillSource = Field(default=SkillSource.USER, description="Skill source")
    requirements: List[str] = Field(default_factory=list, description="Python requirements")
    tools: List[str] = Field(default_factory=list, description="Required tools")
    config_schema: Optional[SkillConfig] = Field(default=None, description="Config schema")
    entrypoint: Optional[str] = Field(default=None, description="Entrypoint script file")
    files: List[str] = Field(default_factory=list, description="List of skill files (excluding skill.md)")
    skill_content: str = Field(..., description="Full skill.md content")
    dir_path: Optional[str] = Field(default=None, description="Directory path if loaded from file")
    enabled: bool = Field(default=True, description="Whether skill is enabled")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_metadata(self) -> SkillMetadata:
        """Get metadata object"""
        return SkillMetadata(
            name=self.name,
            version=self.version,
            description=self.description,
            author=self.author,
            tags=self.tags,
            tools=self.tools,
            config_schema=self.config_schema,
            entrypoint=self.entrypoint,
            files=self.files,
        )


class SkillSummary(BaseModel):
    """Skill summary for initial loading (save tokens)"""
    name: str = Field(..., description="Skill name")
    description: str = Field(default="", description="Skill description")
    tags: List[str] = Field(default_factory=list, description="Tags")


class SkillCreate(BaseModel):
    """Skill creation model"""
    name: str = Field(..., description="Skill name")
    description: str = Field(default="", description="Skill description")
    skill_content: str = Field(..., description="Full skill.md content")
    source: SkillSource = Field(default=SkillSource.USER)


class SkillUpdate(BaseModel):
    """Skill update model"""
    description: Optional[str] = Field(default=None)
    skill_content: Optional[str] = Field(default=None)
    enabled: Optional[bool] = Field(default=None)


class AgentSkillLink(BaseModel):
    """Agent-Skill association"""
    agent_id: str = Field(..., description="Agent ID")
    skill_id: str = Field(..., description="Skill ID")
    enabled: bool = Field(default=True, description="Whether enabled for this agent")
    priority: int = Field(default=0, description="Priority for auto-selection")


class SkillExecuteRequest(BaseModel):
    """Skill execution request"""
    skill_name: str = Field(..., description="Skill name")
    context: Dict[str, Any] = Field(default_factory=dict, description="Execution context")
    config: Dict[str, Any] = Field(default_factory=dict, description="Skill config")


class SkillScaffoldRequest(BaseModel):
    """Skill scaffold request"""
    name: str = Field(..., description="Skill name")
    template: str = Field(default="basic", description="Template name")
    description: str = Field(default="", description="Skill description")
    author: str = Field(default="", description="Author name")
    tags: List[str] = Field(default_factory=list, description="Skill tags")
    tools: List[str] = Field(default_factory=list, description="Required tool names")


class SkillGenerateRequest(BaseModel):
    """LLM generation request"""
    description: str = Field(..., description="Description of the skill to generate")
    template: str = Field(default="basic", description="Template to use")
    requirements: List[str] = Field(default_factory=list, description="Python requirements")


class SkillCompleteRequest(BaseModel):
    """LLM completion request"""
    skill_name: str = Field(..., description="Skill name")
    file_path: str = Field(..., description="File path")
    current_content: str = Field(..., description="Current file content")
    instruction: str = Field(..., description="Instruction for LLM")


class SkillTestRequest(BaseModel):
    """Skill test request"""
    skill_name: str = Field(..., description="Skill name")
    input: Any = Field(..., description="Test input")
    session_id: str = Field(default=None, description="Session ID for state persistence")


class ChatMessage(BaseModel):
    """Chat message for AI assistant"""
    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Chat request for AI assistant"""
    messages: List[ChatMessage] = Field(..., description="Chat history")
    skill_name: str = Field(default=None, description="Current skill name if any")
    current_file: str = Field(default=None, description="Current file being edited")
    file_content: str = Field(default=None, description="Current file content if any")
    skill_type: Optional[str] = Field(default=None, description="Skill type: prompt-only, python, shell, powershell")
