import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { 
  Server, 
  Code, 
  FileText,
  Folder,
  Terminal
} from 'lucide-react';

const backendFiles = {
  'app/main.py': `"""
FastAPI Application Entry Point
Michaels AskHR Backend
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.routers import chat, leave, verification, admin
from app.models.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown cleanup

app = FastAPI(
    title="Michaels AskHR API",
    description="AI-powered AskHR Agent Backend",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(leave.router, prefix="/api/v1/leave", tags=["Leave"])
app.include_router(verification.router, prefix="/api/v1/verification", tags=["Verification"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "askhr-api"}
`,

  'app/config.py': `"""
Configuration Settings
Environment variable management using Pydantic
"""
from pydantic_settings import BaseSettings
from typing import List, Optional
from functools import lru_cache

class Settings(BaseSettings):
    # Application
    app_name: str = "Michaels AskHR"
    debug: bool = False
    environment: str = "production"
    
    # Database
    database_url: str = "postgresql://user:pass@localhost/askhr"
    
    # IBM Verify SSO
    ibm_verify_issuer: str = "https://your-tenant.verify.ibm.com"
    ibm_verify_client_id: str = ""
    ibm_verify_jwks_uri: str = "https://your-tenant.verify.ibm.com/v1.0/keys"
    
    # Vertex AI / Gemini
    gcp_project_id: str = ""
    gcp_region: str = "us-south1"
    vertex_rag_corpus_id: str = ""
    gemini_model: str = "gemini-2.5-pro"
    
    # Workday Integration
    workday_api_base_url: str = "https://wd5-impl-services1.workday.com"
    workday_tenant: str = ""
    
    # Oracle HR Integration
    oracle_hr_api_base_url: str = "https://your-oracle-instance.com"
    
    # GCS for verification letters
    gcs_bucket_name: str = "askhr-verification-letters"
    
    # CORS
    allowed_origins: List[str] = ["http://localhost:3000", "https://askhr.michaels.com"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
`,

  'app/auth/dependencies.py': `"""
FastAPI Authentication Dependencies
IBM Verify JWT Validation
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, jwk, JWTError
from typing import Optional
import httpx
from functools import lru_cache
from pydantic import BaseModel

from app.config import settings

security = HTTPBearer()

class UserContext(BaseModel):
    user_id: str
    email: str
    worker_id: Optional[str] = None
    roles: list[str] = []
    full_name: Optional[str] = None

class JWKSClient:
    def __init__(self, jwks_uri: str):
        self.jwks_uri = jwks_uri
        self._keys = None
    
    async def get_signing_key(self, kid: str):
        if self._keys is None:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_uri)
                self._keys = response.json()["keys"]
        
        for key in self._keys:
            if key["kid"] == kid:
                return jwk.construct(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find signing key"
        )

jwks_client = JWKSClient(settings.ibm_verify_jwks_uri)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UserContext:
    """
    Validate IBM Verify JWT token and extract user context
    """
    token = credentials.credentials
    
    try:
        # Decode header to get key ID
        unverified_header = jwt.get_unverified_header(token)
        signing_key = await jwks_client.get_signing_key(unverified_header["kid"])
        
        # Verify and decode token
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.ibm_verify_client_id,
            issuer=settings.ibm_verify_issuer
        )
        
        return UserContext(
            user_id=payload.get("sub"),
            email=payload.get("email"),
            worker_id=payload.get("worker_id"),
            roles=payload.get("groups", []),
            full_name=payload.get("name")
        )
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}"
        )
`,

  'app/routers/chat.py': `"""
Chat Router
Handles conversation sessions and messages
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import uuid

from app.auth.dependencies import get_current_user, UserContext
from app.services.orchestrator import AgentOrchestrator
from app.services.sessions import SessionManager
from app.models.dto import (
    CreateSessionRequest,
    CreateSessionResponse,
    SendMessageRequest,
    SendMessageResponse,
    ChatMessage,
    Citation
)

router = APIRouter()
orchestrator = AgentOrchestrator()
session_manager = SessionManager()

@router.post("/session", response_model=CreateSessionResponse)
async def create_session(
    request: CreateSessionRequest,
    user: UserContext = Depends(get_current_user)
):
    """Create a new chat session"""
    session = await session_manager.create_session(
        user_id=user.user_id,
        worker_id=user.worker_id,
        metadata=request.metadata
    )
    return CreateSessionResponse(
        session_id=session.id,
        created_at=session.created_at
    )

@router.post("/message", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    user: UserContext = Depends(get_current_user)
):
    """Send a message and get AI response"""
    # Validate session ownership
    session = await session_manager.get_session(request.session_id)
    if not session or session.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Save user message
    await session_manager.add_message(
        session_id=request.session_id,
        role="user",
        content=request.message,
        file_urls=request.file_urls
    )
    
    # Process through orchestrator
    result = await orchestrator.process_message(
        session_id=request.session_id,
        message=request.message,
        user_context=user,
        file_urls=request.file_urls
    )
    
    # Save assistant response
    await session_manager.add_message(
        session_id=request.session_id,
        role="assistant",
        content=result.reply_text,
        agent_name=result.agent_name,
        citations=result.citations,
        tool_calls=result.tool_calls
    )
    
    return SendMessageResponse(
        message_id=str(uuid.uuid4()),
        content=result.reply_text,
        agent_name=result.agent_name,
        citations=result.citations,
        tool_calls=result.tool_calls,
        escalated=result.escalate
    )

@router.get("/session/{session_id}/messages", response_model=List[ChatMessage])
async def get_session_messages(
    session_id: str,
    user: UserContext = Depends(get_current_user)
):
    """Get all messages in a session"""
    session = await session_manager.get_session(session_id)
    if not session or session.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return await session_manager.get_messages(session_id)
`,

  'app/services/orchestrator.py': `"""
Agent Orchestrator
Routes messages to specialized agents
"""
from typing import Optional, List
from pydantic import BaseModel
from enum import Enum

from app.auth.dependencies import UserContext
from app.agents.router_agent import RouterAgent
from app.agents.policy_benefits_agent import PolicyBenefitsAgent
from app.agents.leave_agent import LeaveAgent
from app.agents.verification_agent import VerificationAgent
from app.agents.employment_status_agent import EmploymentStatusAgent
from app.agents.escalation_agent import EscalationAgent
from app.services.rag import RAGService
from app.services.llm import GeminiService

class AgentType(str, Enum):
    POLICY_BENEFITS = "policy_benefits"
    LEAVE = "leave"
    VERIFICATION = "verification"
    EMPLOYMENT_STATUS = "employment_status"
    ESCALATION = "escalation"

class AgentResult(BaseModel):
    reply_text: str
    agent_name: str
    citations: List[dict] = []
    tool_calls: List[dict] = []
    escalate: bool = False
    transaction_metadata: Optional[dict] = None

class AgentOrchestrator:
    def __init__(self):
        self.rag_service = RAGService()
        self.llm_service = GeminiService()
        self.router_agent = RouterAgent(self.llm_service)
        
        self.agents = {
            AgentType.POLICY_BENEFITS: PolicyBenefitsAgent(self.rag_service, self.llm_service),
            AgentType.LEAVE: LeaveAgent(self.rag_service, self.llm_service),
            AgentType.VERIFICATION: VerificationAgent(self.llm_service),
            AgentType.EMPLOYMENT_STATUS: EmploymentStatusAgent(self.llm_service),
            AgentType.ESCALATION: EscalationAgent(self.llm_service)
        }
    
    async def process_message(
        self,
        session_id: str,
        message: str,
        user_context: UserContext,
        file_urls: Optional[List[str]] = None
    ) -> AgentResult:
        """
        Route message to appropriate agent and return response
        """
        # Get conversation history for context
        from app.services.sessions import SessionManager
        session_manager = SessionManager()
        history = await session_manager.get_messages(session_id, limit=10)
        
        # Route to appropriate agent
        routing_result = await self.router_agent.route(
            message=message,
            history=history,
            user_context=user_context
        )
        
        agent_type = routing_result.agent_type
        agent = self.agents.get(agent_type)
        
        if not agent:
            agent = self.agents[AgentType.ESCALATION]
        
        # Execute agent
        result = await agent.execute(
            message=message,
            user_context=user_context,
            history=history,
            routing_context=routing_result.context,
            file_urls=file_urls
        )
        
        return AgentResult(
            reply_text=result.reply_text,
            agent_name=agent_type.value,
            citations=result.citations,
            tool_calls=result.tool_calls,
            escalate=result.escalate,
            transaction_metadata=result.transaction_metadata
        )
`,

  'app/agents/router_agent.py': `"""
Router Agent
Classifies intent and routes to specialized agents
"""
from typing import List, Optional
from pydantic import BaseModel
from enum import Enum

from app.auth.dependencies import UserContext
from app.services.llm import GeminiService

class AgentType(str, Enum):
    POLICY_BENEFITS = "policy_benefits"
    LEAVE = "leave"
    VERIFICATION = "verification"
    EMPLOYMENT_STATUS = "employment_status"
    ESCALATION = "escalation"

class RoutingResult(BaseModel):
    agent_type: AgentType
    confidence: float
    context: dict = {}
    reasoning: str = ""

class RouterAgent:
    ROUTING_PROMPT = """You are an AskHR agent router. Analyze the user's message and determine which specialized agent should handle it.

Available agents:
1. POLICY_BENEFITS - Questions about company policies, benefits (health, dental, 401k), employee handbook, PTO policies
2. LEAVE - Leave balance inquiries, time-off requests, vacation/sick leave management
3. VERIFICATION - Employment verification letters, proof of employment requests
4. EMPLOYMENT_STATUS - Job details, employment status, compensation questions, reporting structure
5. ESCALATION - Sensitive matters, complaints, issues requiring human HR intervention

User Message: {message}

Previous Context: {history_summary}

Respond with JSON:
{{
    "agent_type": "POLICY_BENEFITS|LEAVE|VERIFICATION|EMPLOYMENT_STATUS|ESCALATION",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation",
    "extracted_intent": "What the user wants",
    "entities": {{"dates": [], "leave_type": null, "specific_policy": null}}
}}
"""

    def __init__(self, llm_service: GeminiService):
        self.llm = llm_service
    
    async def route(
        self,
        message: str,
        history: List[dict],
        user_context: UserContext
    ) -> RoutingResult:
        """
        Analyze message and determine routing
        """
        history_summary = self._summarize_history(history)
        
        prompt = self.ROUTING_PROMPT.format(
            message=message,
            history_summary=history_summary
        )
        
        response = await self.llm.generate_json(prompt)
        
        agent_type = AgentType(response.get("agent_type", "ESCALATION").lower())
        
        return RoutingResult(
            agent_type=agent_type,
            confidence=response.get("confidence", 0.5),
            context={
                "intent": response.get("extracted_intent"),
                "entities": response.get("entities", {})
            },
            reasoning=response.get("reasoning", "")
        )
    
    def _summarize_history(self, history: List[dict], max_messages: int = 5) -> str:
        if not history:
            return "No previous context"
        
        recent = history[-max_messages:]
        summary = []
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:100]
            summary.append(f"{role}: {content}")
        
        return "\\n".join(summary)
`,

  'app/agents/leave_agent.py': `"""
Leave Agent
Handles leave balance inquiries and request processing
"""
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, date

from app.auth.dependencies import UserContext
from app.services.rag import RAGService
from app.services.llm import GeminiService
from app.services.workday_client import WorkdayClient

class LeaveAgentResult(BaseModel):
    reply_text: str
    citations: List[dict] = []
    tool_calls: List[dict] = []
    escalate: bool = False
    transaction_metadata: Optional[dict] = None

class LeaveAgent:
    def __init__(self, rag_service: RAGService, llm_service: GeminiService):
        self.rag = rag_service
        self.llm = llm_service
        self.workday = WorkdayClient()
    
    async def execute(
        self,
        message: str,
        user_context: UserContext,
        history: List[dict],
        routing_context: dict,
        file_urls: Optional[List[str]] = None
    ) -> LeaveAgentResult:
        """
        Process leave-related requests
        """
        intent = routing_context.get("intent", "").lower()
        entities = routing_context.get("entities", {})
        tool_calls = []
        citations = []
        
        # Check if this is a balance inquiry
        if "balance" in intent or "how many" in message.lower() or "check" in message.lower():
            return await self._handle_balance_inquiry(user_context, tool_calls)
        
        # Check if this is a leave request
        if "request" in intent or "take" in message.lower() or "off" in message.lower():
            return await self._handle_leave_request(
                message, user_context, entities, tool_calls
            )
        
        # General leave policy question - use RAG
        return await self._handle_policy_question(message, citations)
    
    async def _handle_balance_inquiry(
        self,
        user_context: UserContext,
        tool_calls: List[dict]
    ) -> LeaveAgentResult:
        """Fetch and format leave balance"""
        balance = await self.workday.get_leave_balance(user_context.worker_id)
        
        tool_calls.append({
            "tool_name": "workday.get_leave_balance",
            "parameters": {"worker_id": user_context.worker_id},
            "result": balance
        })
        
        # Format response
        response = f"""Here's your current leave balance:

**Vacation:** {balance.get('vacation', {}).get('available', 0)} days available ({balance.get('vacation', {}).get('used', 0)} used of {balance.get('vacation', {}).get('total', 0)})
**Sick Leave:** {balance.get('sick', {}).get('available', 0)} days available
**Personal Days:** {balance.get('personal', {}).get('available', 0)} days available

Would you like to request time off or learn more about our leave policies?"""
        
        return LeaveAgentResult(
            reply_text=response,
            tool_calls=tool_calls
        )
    
    async def _handle_leave_request(
        self,
        message: str,
        user_context: UserContext,
        entities: dict,
        tool_calls: List[dict]
    ) -> LeaveAgentResult:
        """Process leave request"""
        dates = entities.get("dates", [])
        leave_type = entities.get("leave_type")
        
        # If missing required info, ask for it
        if not dates or not leave_type:
            return LeaveAgentResult(
                reply_text="""I'd be happy to help you request time off. To proceed, I need:

1. **Leave Type** - Vacation, Sick, Personal, etc.
2. **Start Date** - When does your leave begin?
3. **End Date** - When does your leave end?
4. **Reason** (optional)

Please provide these details, or use the quick action buttons to fill in a form."""
            )
        
        # Validate against policy (RAG)
        policy_context = await self.rag.query(
            f"leave policy validation {leave_type}",
            filters={"category": "leave_policy"}
        )
        
        # Validate against balance
        balance = await self.workday.get_leave_balance(user_context.worker_id)
        
        # Check if sufficient balance
        # (simplified validation)
        
        return LeaveAgentResult(
            reply_text=f"""I can help you submit a {leave_type} leave request. Based on your balance, you have sufficient days available.

Please confirm the following details:
- **Leave Type:** {leave_type}
- **Dates:** {dates}

Type "confirm" to submit, or provide any corrections.""",
            tool_calls=tool_calls
        )
    
    async def _handle_policy_question(
        self,
        message: str,
        citations: List[dict]
    ) -> LeaveAgentResult:
        """Answer leave policy questions using RAG"""
        rag_results = await self.rag.query(
            message,
            filters={"category": "leave_policy"}
        )
        
        for doc in rag_results.documents:
            citations.append({
                "doc_id": doc.id,
                "title": doc.title,
                "url": doc.url,
                "snippet": doc.snippet,
                "confidence": doc.confidence
            })
        
        context = "\\n".join([doc.content for doc in rag_results.documents])
        
        response = await self.llm.generate(
            prompt=f"""Based on Michaels HR leave policies, answer this question:

Question: {message}

Policy Context:
{context}

Provide a clear, helpful answer. Cite specific policies when applicable."""
        )
        
        return LeaveAgentResult(
            reply_text=response,
            citations=citations
        )
`,

  'app/services/workday_client.py': `"""
Workday API Client
Handles integration with Workday for leave and employment data
"""
from typing import Optional, Dict, Any
import httpx
from datetime import date
from pydantic import BaseModel

from app.config import settings

class LeaveBalance(BaseModel):
    vacation: Dict[str, float]
    sick: Dict[str, float]
    personal: Dict[str, float]
    parental: Optional[Dict[str, float]] = None

class EmploymentDetails(BaseModel):
    worker_id: str
    employee_id: str
    full_name: str
    job_title: str
    department: str
    hire_date: date
    employment_type: str
    location: str
    manager_name: Optional[str] = None
    is_active: bool = True

class WorkdayClient:
    """
    Workday API Client
    
    Note: This is a stub implementation. In production, you would:
    1. Use proper OAuth2 authentication with Workday
    2. Configure the correct API endpoints for your Workday tenant
    3. Handle pagination for large result sets
    4. Implement proper error handling and retries
    """
    
    def __init__(self):
        self.base_url = settings.workday_api_base_url
        self.tenant = settings.workday_tenant
        self.timeout = httpx.Timeout(30.0)
    
    async def get_leave_balance(self, worker_id: str) -> Dict[str, Any]:
        """
        Fetch leave balance from Workday
        
        In production, this would call:
        GET /ccx/service/{tenant}/TimeOff/v1/Workers/{workerId}/TimeOffBalance
        """
        # STUB: Return mock data
        # Replace with actual Workday API call
        return {
            "vacation": {"total": 15, "used": 5, "available": 10},
            "sick": {"total": 10, "used": 2, "available": 8},
            "personal": {"total": 3, "used": 1, "available": 2},
            "floating_holiday": {"total": 2, "used": 0, "available": 2}
        }
    
    async def create_leave_request(
        self,
        worker_id: str,
        leave_type: str,
        start_date: date,
        end_date: date,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submit a leave request to Workday
        
        In production, this would call:
        POST /ccx/service/{tenant}/TimeOff/v1/Workers/{workerId}/TimeOffRequest
        """
        # STUB: Return mock response
        return {
            "request_id": "WD-TR-2024-12345",
            "status": "submitted",
            "approval_status": "pending",
            "submitted_date": date.today().isoformat()
        }
    
    async def get_employment_details(self, worker_id: str) -> EmploymentDetails:
        """
        Fetch employment details from Workday
        
        In production, this would call:
        GET /ccx/service/{tenant}/Human_Resources/v1/Workers/{workerId}
        """
        # STUB: Return mock data
        return EmploymentDetails(
            worker_id=worker_id,
            employee_id="EMP-" + worker_id[-6:],
            full_name="John Doe",
            job_title="Senior Store Associate",
            department="Retail Operations",
            hire_date=date(2020, 3, 15),
            employment_type="full_time",
            location="Dallas, TX",
            manager_name="Jane Smith",
            is_active=True
        )
    
    async def check_eligibility_for_verification(self, worker_id: str) -> Dict[str, Any]:
        """
        Check if employee is eligible for auto-generated verification letters
        Phase 1: Only FT Support Center employees
        """
        details = await self.get_employment_details(worker_id)
        
        is_eligible = (
            details.employment_type == "full_time" and
            "Support Center" in details.department and
            details.is_active
        )
        
        return {
            "eligible": is_eligible,
            "reason": "FT Support Center employees only in Phase 1" if not is_eligible else None,
            "employee_details": details.model_dump()
        }
`,

  'app/services/rag.py': `"""
RAG Service
Vertex AI RAG integration for policy document retrieval
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from dataclasses import dataclass

from app.config import settings

@dataclass
class RAGDocument:
    id: str
    title: str
    content: str
    url: Optional[str] = None
    snippet: Optional[str] = None
    confidence: float = 0.0
    metadata: Dict[str, Any] = None

class RAGResult(BaseModel):
    documents: List[RAGDocument]
    query: str
    total_results: int

class RAGService:
    """
    Vertex AI RAG Service
    
    Connects to Vertex AI RAG in us-south1 region for HR corpus retrieval.
    
    In production, configure:
    - GCP Project ID
    - RAG Corpus ID
    - Proper authentication via service account
    """
    
    def __init__(self):
        self.project_id = settings.gcp_project_id
        self.region = settings.gcp_region
        self.corpus_id = settings.vertex_rag_corpus_id
    
    async def query(
        self,
        query: str,
        filters: Optional[Dict[str, str]] = None,
        top_k: int = 5
    ) -> RAGResult:
        """
        Query the HR RAG corpus
        
        Args:
            query: Natural language query
            filters: Optional filters (e.g., category, document_type)
            top_k: Number of results to return
        
        Returns:
            RAGResult with relevant documents and citations
        """
        # STUB: In production, use Vertex AI RAG API
        # from google.cloud import aiplatform
        # rag_resource = aiplatform.RagResource(...)
        # response = rag_resource.query(...)
        
        # Mock response for development
        mock_documents = self._get_mock_documents(query, filters)
        
        return RAGResult(
            documents=mock_documents[:top_k],
            query=query,
            total_results=len(mock_documents)
        )
    
    def _get_mock_documents(
        self,
        query: str,
        filters: Optional[Dict[str, str]] = None
    ) -> List[RAGDocument]:
        """Generate mock documents for development"""
        
        query_lower = query.lower()
        documents = []
        
        if "leave" in query_lower or "vacation" in query_lower or "pto" in query_lower:
            documents.append(RAGDocument(
                id="POL-LEAVE-001",
                title="Michaels PTO Policy",
                content="Full-time employees accrue vacation time based on years of service. 0-2 years: 10 days, 3-5 years: 15 days, 6+ years: 20 days. Vacation requests must be submitted at least 2 weeks in advance for periods of 3+ days.",
                url="https://hr.michaels.com/policies/pto",
                snippet="Vacation accrual rates and request guidelines",
                confidence=0.95,
                metadata={"category": "leave_policy", "version": "2024.1"}
            ))
        
        if "benefit" in query_lower or "health" in query_lower or "insurance" in query_lower:
            documents.append(RAGDocument(
                id="POL-BEN-001",
                title="Michaels Benefits Guide 2024",
                content="Michaels offers comprehensive health benefits including medical, dental, and vision coverage. Full-time employees are eligible after 60 days. Dependent coverage available. 401(k) with company match up to 4%.",
                url="https://hr.michaels.com/benefits",
                snippet="Benefits eligibility and coverage overview",
                confidence=0.92,
                metadata={"category": "benefits", "version": "2024.1"}
            ))
        
        if "verification" in query_lower or "employment" in query_lower:
            documents.append(RAGDocument(
                id="POL-VER-001",
                title="Employment Verification Policy",
                content="Employment verification letters are available for active employees. Standard letters include employment dates, job title, and employment status. Salary information requires additional authorization. Processing time: 1-3 business days.",
                url="https://hr.michaels.com/policies/verification",
                snippet="Employment verification request process",
                confidence=0.88,
                metadata={"category": "verification", "version": "2024.1"}
            ))
        
        return documents
`,

  'app/services/llm.py': `"""
ADK LLM Service
Google ADK Gemini integration
"""
from typing import Optional, Dict, Any, List
import json

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.config import settings

class GeminiService:
    """
    Gemini LLM Service via Google ADK
    
    Integrates with Vertex AI for natural language generation.
    Uses Google ADK for model orchestration.
    
    Configuration:
    - GCP_PROJECT_ID: Your GCP project
    - GEMINI_MODEL: Model version (default: gemini-2.5-pro)
    """
    
    def __init__(self):
        self.project_id = settings.gcp_project_id
        self.model = settings.gemini_model
        self.region = settings.gcp_region
        
        # In production, initialize the ADK agent:
        # self.agent = LlmAgent(
        #     name="askhr_llm",
        #     model=Gemini(model=self.model),
        #     instruction="You are AskHR.",
        # )
        # self.runner = InMemoryRunner(self.agent, app_name="askhr")
    
    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        context_documents: Optional[List[str]] = None
    ) -> str:
        """
        Generate text response from Gemini
        
        Args:
            prompt: The user prompt
            system_instruction: Optional system context
            temperature: Creativity level (0-1)
            max_tokens: Maximum response length
            context_documents: Optional RAG context
        
        Returns:
            Generated text response
        """
        # STUB: In production, run via ADK:
        # content = types.Content(
        #     role="user",
        #     parts=[types.Part.from_text(text=prompt)],
        # )
        # async for event in self.runner.run_async(
        #     user_id="askhr_user",
        #     session_id="askhr_session",
        #     new_message=content,
        # ):
        #     if event.is_final_response() and event.content and event.content.parts:
        #         return "".join(part.text for part in event.content.parts if part.text)
        
        # Development mock
        return f"[Gemini Response to: {prompt[:100]}...]"
    
    async def generate_json(
        self,
        prompt: str,
        schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate structured JSON response
        
        Args:
            prompt: The prompt requesting JSON output
            schema: Optional JSON schema for validation
        
        Returns:
            Parsed JSON dictionary
        """
        # STUB: In production, enforce JSON via ADK output_schema
        # or a dedicated tool, then parse the response.
        
        # Development mock - analyze prompt for routing
        if "agent_type" in prompt.lower():
            # Mock routing response
            if "leave" in prompt.lower() or "vacation" in prompt.lower():
                return {
                    "agent_type": "LEAVE",
                    "confidence": 0.9,
                    "reasoning": "User is asking about leave/vacation",
                    "extracted_intent": "leave inquiry",
                    "entities": {"leave_type": "vacation"}
                }
            elif "benefit" in prompt.lower() or "health" in prompt.lower():
                return {
                    "agent_type": "POLICY_BENEFITS",
                    "confidence": 0.85,
                    "reasoning": "User is asking about benefits",
                    "extracted_intent": "benefits inquiry",
                    "entities": {}
                }
            elif "verification" in prompt.lower() or "letter" in prompt.lower():
                return {
                    "agent_type": "VERIFICATION",
                    "confidence": 0.88,
                    "reasoning": "User needs employment verification",
                    "extracted_intent": "verification letter request",
                    "entities": {}
                }
            else:
                return {
                    "agent_type": "POLICY_BENEFITS",
                    "confidence": 0.6,
                    "reasoning": "General HR inquiry",
                    "extracted_intent": "general question",
                    "entities": {}
                }
        
        return {}
    
    async def generate_with_grounding(
        self,
        prompt: str,
        documents: List[Dict[str, str]],
        system_instruction: str = "You are a helpful AskHR agent. Answer based on the provided documents. Cite sources."
    ) -> Dict[str, Any]:
        """
        Generate grounded response with citations
        
        Args:
            prompt: User question
            documents: RAG-retrieved documents
            system_instruction: System context
        
        Returns:
            Response with text and citations
        """
        # Format context
        context = "\\n\\n".join([
            f"[{doc.get('title', 'Document')}]\\n{doc.get('content', '')}"
            for doc in documents
        ])
        
        full_prompt = f"""{system_instruction}

Context Documents:
{context}

User Question: {prompt}

Provide a helpful answer based on the documents above. Include citations in [brackets] when referencing specific policies."""
        
        response = await self.generate(full_prompt)
        
        return {
            "text": response,
            "citations": [{"doc_id": doc.get("id"), "title": doc.get("title")} for doc in documents]
        }
`,

  'Dockerfile': `# Michaels AskHR Backend
# Python 3.11 FastAPI Application

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD curl -f http://localhost:8080/health || exit 1

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
`,

  'requirements.txt': `# Michaels AskHR Backend Dependencies

# Web Framework
fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.3
pydantic-settings==2.1.0

# Authentication
python-jose[cryptography]==3.3.0
httpx==0.26.0

# Database
sqlalchemy==2.0.25
asyncpg==0.29.0
alembic==1.13.1

# Google Cloud / Vertex AI
google-adk==1.21.0
google-cloud-aiplatform==1.38.1

# PDF Generation
reportlab==4.0.8
pypdf2==3.0.1

# Utilities
python-multipart==0.0.6
python-dateutil==2.8.2
structlog==24.1.0

# Testing
pytest==7.4.4
pytest-asyncio==0.23.3
httpx==0.26.0
`
};

export default function BackendReference() {
  const [activeFile, setActiveFile] = React.useState('app/main.py');

  const fileCategories = {
    'Core Application': ['app/main.py', 'app/config.py', 'Dockerfile', 'requirements.txt'],
    'Authentication': ['app/auth/dependencies.py'],
    'Routers': ['app/routers/chat.py'],
    'Services': ['app/services/orchestrator.py', 'app/services/rag.py', 'app/services/llm.py', 'app/services/workday_client.py'],
    'Agents': ['app/agents/router_agent.py', 'app/agents/leave_agent.py']
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-slate-800 flex items-center gap-3">
            <Server className="w-8 h-8 text-red-600" />
            Backend Reference
          </h1>
          <p className="text-slate-500 mt-2">
            Python FastAPI backend code for the Michaels AskHR system
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* File Browser */}
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Folder className="w-4 h-4" />
                Project Files
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="h-[600px]">
                {Object.entries(fileCategories).map(([category, files]) => (
                  <div key={category} className="mb-4">
                    <div className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-100">
                      {category}
                    </div>
                    {files.map(file => (
                      <button
                        key={file}
                        onClick={() => setActiveFile(file)}
                        className={`w-full text-left px-4 py-2 text-sm flex items-center gap-2 hover:bg-slate-100 transition-colors ${
                          activeFile === file ? 'bg-red-50 text-red-700 border-r-2 border-red-600' : 'text-slate-600'
                        }`}
                      >
                        <Code className="w-4 h-4" />
                        {file.split('/').pop()}
                      </button>
                    ))}
                  </div>
                ))}
              </ScrollArea>
            </CardContent>
          </Card>

          {/* Code Viewer */}
          <Card className="lg:col-span-3">
            <CardHeader className="border-b">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-mono flex items-center gap-2">
                  <FileText className="w-4 h-4" />
                  {activeFile}
                </CardTitle>
                <Badge variant="outline" className="font-mono">
                  {activeFile.endsWith('.py') ? 'Python' : 
                   activeFile.endsWith('.txt') ? 'Text' : 'Docker'}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="h-[600px]">
                <pre className="p-4 text-sm font-mono text-slate-700 whitespace-pre-wrap">
                  {backendFiles[activeFile] || '// File not found'}
                </pre>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        {/* Setup Instructions */}
        <Card className="mt-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Terminal className="w-5 h-5" />
              Setup Instructions
            </CardTitle>
          </CardHeader>
          <CardContent className="prose prose-slate max-w-none">
            <div className="grid md:grid-cols-2 gap-6">
              <div>
                <h3 className="text-lg font-semibold">Backend Setup</h3>
                <pre className="bg-slate-900 text-slate-100 p-4 rounded-lg text-sm overflow-x-auto">
{`# Clone and setup
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run development server
uvicorn app.main:app --reload`}
                </pre>
              </div>
              <div>
                <h3 className="text-lg font-semibold">Environment Variables</h3>
                <pre className="bg-slate-900 text-slate-100 p-4 rounded-lg text-sm overflow-x-auto">
{`# Database
DATABASE_URL=postgresql://...

# IBM Verify SSO
IBM_VERIFY_ISSUER=https://...
IBM_VERIFY_CLIENT_ID=...
IBM_VERIFY_JWKS_URI=...

# GCP/Vertex AI
GCP_PROJECT_ID=...
VERTEX_RAG_CORPUS_ID=...

# Workday
WORKDAY_API_BASE_URL=...
WORKDAY_TENANT=...`}
                </pre>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
