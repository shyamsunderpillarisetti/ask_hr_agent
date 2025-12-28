from fastapi import APIRouter, Depends, HTTPException
import logging
from app.auth.dependencies import get_current_user
from app.models.dto import UserContext, CreateSessionRequest, SessionResponse, ChatMessage, ChatResponse
from app.services.orchestrator import RouterAgent
import uuid
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)
orchestrator = RouterAgent()
GREETING_MESSAGE = "Hello! I'm the AskHR agent for Michaels."

# In-memory session store for MVP
sessions = {}

@router.post("/session", response_model=SessionResponse)
async def create_session(_request: CreateSessionRequest, user: UserContext = Depends(get_current_user)):
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "user_id": user.user_id,
        "history": [{"role": "assistant", "content": GREETING_MESSAGE}],
        "created_at": datetime.now()
    }
    return SessionResponse(session_id=session_id, created_at=sessions[session_id]["created_at"])

@router.post("/message", response_model=ChatResponse)
async def send_message(message: ChatMessage, user: UserContext = Depends(get_current_user)):
    if message.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[message.session_id]
    
    try:
        # Process with orchestrator
        response = await orchestrator.route_and_process(
            message.content,
            user,
            session["history"],
            message.session_id,
        )
        
        # Update history
        session["history"].append({"role": "user", "content": message.content})
        session["history"].append({"role": "assistant", "content": response.reply_text})
        
        return response
    except Exception as e:
        logger.exception("Chat message processing failed")
        raise HTTPException(status_code=500, detail=str(e))
