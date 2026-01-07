from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

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


class RagQuery(BaseModel):
    session_id: str
    user_id: str
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

class RagRetrieveRequest(BaseModel):
    query: str

class RagRetrieveResponse(BaseModel):
    contexts: List[str] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)

class LeaveBalance(BaseModel):
    leave_type: str
    balance_hours: float
    balance_days: float
    unit: str

class LeaveRequestPayload(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    leave_type: str
    reason: Optional[str] = None

class VerificationRequest(BaseModel):
    purpose: str
    recipient_email: Optional[str] = None
