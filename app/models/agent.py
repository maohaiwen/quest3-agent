"""Agent models for intelligent assistant configuration"""
from pydantic import BaseModel, Field
from datetime import datetime
from app.utils.timezone import beijing_now
from typing import Optional, List, Dict, Any
from enum import Enum


class AgentType(str, Enum):
    """Agent type enum"""
    CHAT = "chat"
    CODER = "coder"
    RESEARCHER = "researcher"
    CUSTOM = "custom"


class ToolPermission(str, Enum):
    """Tool permission level"""
    REQUIRED = "required"  # Must use this tool
    OPTIONAL = "optional"  # Can use this tool
    FORBIDDEN = "forbidden"  # Cannot use this tool


class AgentToolConfig(BaseModel):
    """Tool configuration for agent"""
    tool_name: str = Field(..., description="Tool name")
    permission: ToolPermission = Field(default=ToolPermission.OPTIONAL, description="Permission level")
    description: Optional[str] = Field(default=None, description="Custom description")


class AgentMCPServerConfig(BaseModel):
    """MCP server configuration for agent"""
    server_id: str = Field(..., description="MCP server ID")
    server_name: str = Field(..., description="MCP server name")
    enabled: bool = Field(default=True, description="Whether this server is enabled")


class AgentCreate(BaseModel):
    """Agent creation model"""
    name: str = Field(..., description="Agent name")
    description: str = Field(default="", description="Agent description")
    type: AgentType = Field(default=AgentType.CUSTOM, description="Agent type")
    execution_mode: str = Field(default="plan", description="Execution mode: plan, react, or direct")
    system_prompt: str = Field(default="", description="System prompt for the agent")
    model: Optional[str] = Field(default=None, description="LLM model to use")
    temperature: Optional[float] = Field(default=None, description="Temperature for generation")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens")
    mcp_servers: List[str] = Field(default_factory=list, description="List of MCP server IDs")
    tools: List[str] = Field(default_factory=list, description="List of enabled tool names")
    skills: List[str] = Field(default_factory=list, description="List of skill names to enable for this agent")
    enabled: bool = Field(default=True, description="Whether agent is enabled")
    priority: int = Field(default=0, description="Priority for auto-selection")
    thinking_effort: str = Field(default="medium", description="Thinking depth: low, medium, high")
    max_react_steps: int = Field(default=15, description="Maximum ReAct steps")
    enable_long_term_memory: bool = Field(default=False, description="Enable agent-level long-term memory")


class AgentUpdate(BaseModel):
    """Agent update model"""
    name: Optional[str] = Field(default=None, description="Agent name")
    description: Optional[str] = Field(default=None, description="Agent description")
    type: Optional[AgentType] = Field(default=None, description="Agent type")
    execution_mode: Optional[str] = Field(default=None, description="Execution mode")
    system_prompt: Optional[str] = Field(default=None, description="System prompt")
    model: Optional[str] = Field(default=None, description="LLM model")
    temperature: Optional[float] = Field(default=None, description="Temperature")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens")
    mcp_servers: Optional[List[str]] = Field(default=None, description="MCP server IDs")
    tools: Optional[List[str]] = Field(default=None, description="List of enabled tool names")
    skills: Optional[List[str]] = Field(default=None, description="List of skill names to enable")
    enabled: Optional[bool] = Field(default=None, description="Enabled status")
    priority: Optional[int] = Field(default=None, description="Priority")
    thinking_effort: Optional[str] = Field(default=None, description="Thinking depth")
    max_react_steps: Optional[int] = Field(default=None, description="Maximum ReAct steps")
    enable_long_term_memory: Optional[bool] = Field(default=None, description="Enable agent-level long-term memory")


class AgentResponse(BaseModel):
    """Agent response model"""
    id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="Agent name")
    description: str = Field(default="", description="Agent description")
    type: AgentType = Field(default=AgentType.CUSTOM, description="Agent type")
    execution_mode: str = Field(default="plan", description="Execution mode")
    system_prompt: str = Field(default="", description="System prompt")
    model: Optional[str] = Field(default=None, description="LLM model")
    temperature: Optional[float] = Field(default=None, description="Temperature")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens")
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list, description="MCP servers")
    tools: List[str] = Field(default_factory=list, description="List of enabled tool names")
    skills: List[str] = Field(default_factory=list, description="List of enabled skill names")
    enabled: bool = Field(default=True, description="Enabled status")
    priority: int = Field(default=0, description="Priority")
    created_at: datetime = Field(default_factory=beijing_now, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=beijing_now, description="Update timestamp")
    usage_count: int = Field(default=0, description="Usage count")
    thinking_effort: str = Field(default="medium", description="Thinking depth")
    max_react_steps: int = Field(default=15, description="Maximum ReAct steps")
    enable_long_term_memory: bool = Field(default=False, description="Enable agent-level long-term memory")


class AgentSelectRequest(BaseModel):
    """Agent selection request"""
    session_id: Optional[str] = Field(default=None, description="Session ID")
    message: str = Field(..., description="User message")
    conversation_history: Optional[List[Dict[str, Any]]] = Field(default=None, description="Conversation history")

