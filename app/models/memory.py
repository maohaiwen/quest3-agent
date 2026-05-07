"""Memory models"""
from pydantic import BaseModel, Field
from datetime import datetime
from app.utils.timezone import beijing_now
from typing import Optional, List, Dict, Any


class MemoryStoreRequest(BaseModel):
    """Memory store request model"""
    session_id: str = Field(..., description="Session ID")
    content: str = Field(..., description="Content to store")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")


class MemorySearchRequest(BaseModel):
    """Memory search request model"""
    query: str = Field(..., description="Search query")
    session_id: str = Field(..., description="Session ID")
    limit: int = Field(default=5, description="Number of results")


class MemoryItem(BaseModel):
    """Memory item model"""
    id: str = Field(..., description="Memory ID")
    session_id: str = Field(..., description="Session ID")
    content: str = Field(..., description="Content")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Metadata")
    created_at: datetime = Field(default_factory=beijing_now, description="Creation timestamp")


class MemorySearchResponse(BaseModel):
    """Memory search response model"""
    results: List[MemoryItem] = Field(default_factory=list, description="Search results")
    query: str = Field(..., description="Search query")
    count: int = Field(default=0, description="Result count")


class MemoryStoreResponse(BaseModel):
    """Memory store response model"""
    memory_id: str = Field(..., description="Memory ID")
    created_at: datetime = Field(default_factory=beijing_now, description="Creation timestamp")
