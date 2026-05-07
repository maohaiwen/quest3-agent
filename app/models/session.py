"""Session models"""
from pydantic import BaseModel, Field
from datetime import datetime
from app.utils.timezone import beijing_now
from typing import Optional
from enum import Enum


class SessionStatus(str, Enum):
    """Session status enum"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class SessionCreate(BaseModel):
    """Session creation model"""
    user_id: Optional[str] = Field(default=None, description="User ID")
    title: Optional[str] = Field(default=None, description="Session title")
    agent_id: Optional[str] = Field(default=None, description="Agent ID")


class SessionUpdate(BaseModel):
    """Session update model"""
    title: Optional[str] = Field(default=None, description="Session title")
    status: Optional[SessionStatus] = Field(default=None, description="Session status")


class SessionResponse(BaseModel):
    """Session response model"""
    id: str = Field(..., description="Session ID")
    user_id: Optional[str] = Field(default=None, description="User ID")
    title: Optional[str] = Field(default=None, description="Session title")
    agent_id: Optional[str] = Field(default=None, description="Agent ID")
    status: SessionStatus = Field(default=SessionStatus.ACTIVE, description="Session status")
    created_at: datetime = Field(default_factory=beijing_now, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=beijing_now, description="Update timestamp")
    message_count: int = Field(default=0, description="Message count")


class SessionCreateResponse(BaseModel):
    """Session creation response model"""
    session_id: str = Field(..., description="Session ID")
    created_at: datetime = Field(default_factory=beijing_now, description="Creation timestamp")
