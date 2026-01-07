import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.models.dto import ChatMessage, ChatResponse, CreateSessionRequest, SessionResponse, UserContext
from app.services.router_service import RouterAgent, GREETING_MESSAGE

router = APIRouter()
logger = logging.getLogger(__name__)
_orchestrator = None

# In-memory session store for MVP
sessions = {}


@router.post("/session", response_model=SessionResponse)
async def create_session(_request: CreateSessionRequest, user: UserContext = Depends(get_current_user)):
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "user_id": user.user_id,
        "history": [{"role": "assistant", "content": GREETING_MESSAGE}],
        "last_route": None,
        "awaiting_workday": False,
        "created_at": datetime.now(),
    }
    return SessionResponse(session_id=session_id, created_at=sessions[session_id]["created_at"])


@router.post("/message", response_model=ChatResponse)
async def send_message(message: ChatMessage, user: UserContext = Depends(get_current_user)):
    if message.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[message.session_id]

    try:
        response = await _get_orchestrator().route_and_process(
            message.content,
            user,
            session,
            message.session_id,
        )

        route = response.metadata.get("route") if response.metadata else None
        if route:
            session["last_route"] = route
            if route == "workday" and "?" in response.reply_text:
                session["awaiting_workday"] = True
            else:
                session["awaiting_workday"] = False

        session["history"].append({"role": "user", "content": message.content})
        assistant_entry = {"role": "assistant", "content": response.reply_text}
        if route:
            assistant_entry["route"] = route
        session["history"].append(assistant_entry)

        return response
    except Exception as e:
        logger.exception("Chat message processing failed")
        raise HTTPException(status_code=500, detail=str(e))


def _get_orchestrator() -> RouterAgent:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RouterAgent()
    return _orchestrator
