"""Chat message models"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum


class MessageRole(str, Enum):
    """Message role enum"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageCreate(BaseModel):
    """Message creation model"""
    session_id: str = Field(..., description="Session ID")
    content: str = Field(..., description="Message content")
    role: MessageRole = Field(default=MessageRole.USER, description="Message role")


class MessageResponse(BaseModel):
    """Message response model"""
    id: str = Field(..., description="Message ID")
    session_id: str = Field(..., description="Session ID")
    content: str = Field(..., description="Message content")
    role: MessageRole = Field(..., description="Message role")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")


class ChatRequest(BaseModel):
    """Chat request model"""
    session_id: str = Field(..., description="Session ID")
    message: str = Field(..., description="User message")
    deep_thinking: bool = Field(default=False, description="Enable deep thinking mode")


class ChatResponse(BaseModel):
    """Chat response model"""
    response: str = Field(..., description="AI response")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    message_id: str = Field(..., description="Message ID")
    session_id: str = Field(..., description="Session ID")


class StreamMessage(BaseModel):
    """WebSocket stream message"""
    type: str = Field(..., description="Message type: 'message', 'error', 'end'")
    content: str = Field(default="", description="Message content")
    session_id: str = Field(..., description="Session ID")
