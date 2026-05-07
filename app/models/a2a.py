"""A2A (Agent-to-Agent) Protocol Models compatible with Google A2A specification"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from app.utils.timezone import beijing_now
from enum import Enum


class A2APartType(str, Enum):
    """A2A message part type"""
    TEXT = "text"
    FILE = "file"
    DATA = "data"


class A2APart(BaseModel):
    """A2A message part - can be text, file, or structured data"""
    type: A2APartType = A2APartType.TEXT
    content: str = Field(default="", description="Text content, file URL, or JSON string")


class A2AMessageRole(str, Enum):
    """A2A message role - Google A2A only defines user and agent"""
    USER = "user"
    AGENT = "agent"


class A2AMessage(BaseModel):
    """A2A protocol message"""
    role: A2AMessageRole = A2AMessageRole.USER
    parts: List[A2APart] = Field(default_factory=list, description="Multi-part message content")
    timestamp: str = Field(default_factory=lambda: beijing_now().isoformat())

    def get_text(self) -> str:
        """Get concatenated text from all text parts"""
        return " ".join(part.content for part in self.parts if part.type == A2APartType.TEXT)


class A2ATaskStatusState(str, Enum):
    """A2A task status state"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class A2ATaskStatus(BaseModel):
    """A2A task status"""
    state: A2ATaskStatusState = A2ATaskStatusState.PENDING
    message: Optional[str] = None


class A2ATask(BaseModel):
    """A2A Task - compatible with Google A2A specification"""
    id: str = Field(..., description="Unique task ID")
    status: A2ATaskStatus = Field(default_factory=A2ATaskStatus)
    input: str = Field(default="", description="Task input text")
    output: Optional[str] = Field(default=None, description="Task output text")
    messages: List[A2AMessage] = Field(default_factory=list, description="Message history for this task")
    created_at: str = Field(default_factory=lambda: beijing_now().isoformat())
    updated_at: str = Field(default_factory=lambda: beijing_now().isoformat())

    def add_message(self, role: A2AMessageRole, text: str):
        """Add a message to the task"""
        msg = A2AMessage(
            role=role,
            parts=[A2APart(type=A2APartType.TEXT, content=text)]
        )
        self.messages.append(msg)
        self.updated_at = beijing_now().isoformat()

    def set_completed(self, output: str):
        """Mark task as completed with output"""
        self.status.state = A2ATaskStatusState.COMPLETED
        self.output = output
        self.updated_at = beijing_now().isoformat()

    def set_failed(self, error: str):
        """Mark task as failed with error message"""
        self.status.state = A2ATaskStatusState.FAILED
        self.status.message = error
        self.updated_at = beijing_now().isoformat()


class AgentCard(BaseModel):
    """A2A Agent Card - exposed at /.well-known/agent.json (Google A2A spec)"""
    name: str = Field(..., description="Agent name")
    description: str = Field(default="", description="Agent description")
    url: str = Field(..., description="A2A service endpoint URL")
    version: str = Field(default="1.0.0", description="Agent version")
    capabilities: List[str] = Field(default_factory=list, description="List of agent capabilities")

    # Extension fields for internal use (not part of standard A2A but stored for convenience)
    agent_id: Optional[str] = Field(default=None, description="Internal agent ID (maps to agents table)")
    role: Optional[str] = Field(default=None, description="Collaboration role: supervisor/generator/discriminator/judge/child")


class A2ATaskRequest(BaseModel):
    """Request to create an A2A task"""
    input: str = Field(..., description="Task input text")
    session_id: Optional[str] = None
    context: Optional[dict] = None
