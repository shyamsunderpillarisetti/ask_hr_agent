from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    user_id: str
    worker_id: str
    email: str
    name: str
    roles: List[str] = []


class CreateSessionRequest(BaseModel):
    initial_message: Optional[str] = None


class SessionResponse(BaseModel):
    session_id: str
    created_at: datetime


class ChatMessage(BaseModel):
    session_id: str
    content: str


class Citation(BaseModel):
    title: str
    url: Optional[str] = None
    snippet: Optional[str] = None
    confidence: Optional[float] = None


class ChatResponse(BaseModel):
    reply_text: str
    citations: List[Citation] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RouteDecision(BaseModel):
    route: str
    reason: Optional[str] = None
    confidence: Optional[float] = None
