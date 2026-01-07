import logging
import re
from typing import Dict

from app.config import settings
from app.models.dto import ChatResponse, RouteDecision, UserContext
from app.services.rag_service import RagService
from app.services.routing import RoutingAgent
from app.services.workday_tools import WorkdayToolsService

logger = logging.getLogger(__name__)

GREETING_MESSAGE = "Hello! I'm the AskHR agent for Michaels."


class RouterAgent:
    def __init__(self):
        self.routing_agent = RoutingAgent()
        self.rag_service = RagService(settings.RAG_SERVICE_URL)
        self.workday_tools = WorkdayToolsService(settings.WORKDAY_TOOLS_URL)

    async def route_and_process(
        self,
        query: str,
        user_context: UserContext,
        session_state: Dict,
        session_id: str,
    ) -> ChatResponse:
        history = session_state.get("history", []) if isinstance(session_state, dict) else []
        q = query.strip().lower()
        if self._is_greeting(q):
            reply_text = "How can I help you today?" if history else GREETING_MESSAGE
            return ChatResponse(
                reply_text=reply_text,
                metadata={"agent": "system"},
            )

        user_id = user_context.user_id or "anonymous"
        if self._should_force_workday(query, session_state):
            decision = RouteDecision(
                route="workday",
                reason="Follow-up to Workday prompt",
                confidence=1.0,
            )
        else:
            decision = await self.routing_agent.decide_route(query, user_id, session_id, history)

        if decision.route == "workday":
            response = await self.workday_tools.chat(query)
        else:
            response = await self.rag_service.query(query, session_id, user_id)

        response.metadata = {
            **(response.metadata or {}),
            "route": decision.route,
            "route_reason": decision.reason,
            "route_confidence": decision.confidence,
        }
        return response

    @staticmethod
    def _is_greeting(text: str) -> bool:
        if not text:
            return False
        greeting_pattern = re.compile(
            r"^((hi|hello|hey|hiya|howdy|yo|sup)( there)?|(good morning|good afternoon|good evening|morning|afternoon|evening))([!.,]?)$"
        )
        return greeting_pattern.match(text) is not None

    @staticmethod
    def _should_force_workday(query: str, session_state: Dict) -> bool:
        if not isinstance(session_state, dict):
            return False
        if not session_state.get("awaiting_workday"):
            return False
        return RouterAgent._looks_like_workday_followup(query)

    @staticmethod
    def _looks_like_workday_followup(text: str) -> bool:
        if not text:
            return False
        normalized = text.strip().lower()
        if normalized in {"yes", "no", "yep", "yeah", "nah"}:
            return True

        date_pattern = re.compile(
            r"\b(today|tomorrow|yesterday|next week|this week|next month|this month|"
            r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
            r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b"
        )
        numeric_date_pattern = re.compile(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b")
        duration_pattern = re.compile(r"\b\d+(\.\d+)?\s*(hours?|hrs?)\b")
        day_fraction_pattern = re.compile(r"\b(half|full)\s*day\b")
        leave_type_pattern = re.compile(r"\b(sick|vacation|pto|personal|bereavement|jury)\b")

        if (
            date_pattern.search(normalized)
            or numeric_date_pattern.search(normalized)
            or duration_pattern.search(normalized)
            or day_fraction_pattern.search(normalized)
            or leave_type_pattern.search(normalized)
        ):
            return True

        return False
