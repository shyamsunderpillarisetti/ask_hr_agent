import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.dto import RouteDecision

logger = logging.getLogger(__name__)

ROUTING_INSTRUCTION = """You are the AskHR router for Michaels.

Decide which backend should handle the request:
- route "workday" for time off, leave balances, employment verification letters, or any Workday data/actions.
- route "rag" for policy, benefits, and general HR questions that don't require Workday actions.

Return ONLY JSON:
{"route": "rag" | "workday", "confidence": 0.0-1.0, "reason": "short reason"}
"""


class RoutingAgent:
    def __init__(self):
        self._vertex_initialized = False
        self._genai_loaded = False
        self._LlmAgent = None
        self._Gemini = None
        self._InMemoryRunner = None
        self._adk_vertexai = None
        self._types = None
        self._ensure_vertex_env()
        self._agent = None
        self._runner = None

    def _load_genai(self) -> None:
        if self._genai_loaded:
            return
        from google.adk.agents import LlmAgent  # pylint: disable=import-error
        from google.adk.dependencies import vertexai as adk_vertexai  # pylint: disable=import-error
        from google.adk.models import Gemini  # pylint: disable=import-error
        from google.adk.runners import InMemoryRunner  # pylint: disable=import-error
        from google.genai import types  # pylint: disable=import-error

        self._LlmAgent = LlmAgent
        self._Gemini = Gemini
        self._InMemoryRunner = InMemoryRunner
        self._adk_vertexai = adk_vertexai
        self._types = types
        self._genai_loaded = True

    def _ensure_vertex_env(self) -> None:
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.GOOGLE_PROJECT_ID)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.GOOGLE_LOCATION)

    def _ensure_vertex_init(self) -> None:
        self._load_genai()
        if self._vertex_initialized:
            return
        self._adk_vertexai.vertexai.init(
            project=settings.GOOGLE_PROJECT_ID,
            location=settings.GOOGLE_LOCATION,
            api_transport="rest",
        )
        self._vertex_initialized = True

    def _build_agent(self):
        return self._LlmAgent(
            name="ask_hr_router",
            model=self._Gemini(model=settings.ROUTER_MODEL),
            instruction=ROUTING_INSTRUCTION,
            generate_content_config=self._types.GenerateContentConfig(temperature=0.0),
        )

    def _ensure_agent(self) -> None:
        if self._agent is None:
            self._agent = self._build_agent()
            self._runner = self._InMemoryRunner(self._agent, app_name="ask_hr_router")

    async def decide_route(
        self, query: str, user_id: str, session_id: str, history: Optional[List[Dict]] = None
    ) -> RouteDecision:
        self._ensure_vertex_init()
        self._ensure_agent()

        routing_session_id = f"route-{session_id}-{uuid.uuid4()}"
        await self._ensure_session(user_id, routing_session_id)
        prompt_text = self._build_prompt(query, history or [])
        content = self._types.Content(role="user", parts=[self._types.Part.from_text(text=prompt_text)])

        reply_text = ""
        async for event in self._runner.run_async(
            user_id=user_id,
            session_id=routing_session_id,
            new_message=content,
        ):
            if event.is_final_response():
                reply_text = self._extract_text(event.content) or reply_text

        decision = self._parse_decision(reply_text, query)
        logger.info("Routing decision: %s", decision.model_dump())
        return decision

    async def _ensure_session(self, user_id: str, session_id: str) -> None:
        session_service = self._runner.session_service
        app_name = self._runner.app_name
        session = await session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )
        if session is None:
            await session_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
            )

    @staticmethod
    def _extract_text(content: Optional[Any]) -> str:
        if not content or not content.parts:
            return ""
        return "".join(
            part.text for part in content.parts if part.text and not getattr(part, "thought", False)
        )

    @staticmethod
    def _parse_decision(text: str, fallback_query: str) -> RouteDecision:
        payload = None
        if text:
            try:
                payload = json.loads(text)
            except Exception:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    try:
                        payload = json.loads(match.group(0))
                    except Exception:
                        payload = None

        if isinstance(payload, dict):
            route = str(payload.get("route", "")).strip().lower()
            if route in ("rag", "workday"):
                confidence = payload.get("confidence")
                return RouteDecision(
                    route=route,
                    reason=payload.get("reason"),
                    confidence=confidence if isinstance(confidence, (int, float)) else None,
                )

        return RouteDecision(
            route=RoutingAgent._fallback_route(fallback_query),
            reason="Fallback routing",
            confidence=0.2,
        )

    @staticmethod
    def _fallback_route(query: str) -> str:
        text = query.lower()
        workday_keywords = [
            "leave",
            "time off",
            "pto",
            "sick",
            "vacation",
            "balance",
            "verification",
            "employment letter",
            "workday",
        ]
        if any(keyword in text for keyword in workday_keywords):
            return "workday"
        return "rag"

    @staticmethod
    def _build_prompt(query: str, history: List[Dict], limit: int = 6) -> str:
        if not history:
            return query
        recent = history[-limit:]
        lines = []
        for entry in recent:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            lines.append(f"{role}: {content}")
        context = "\n".join(lines)
        return f"Conversation context:\n{context}\nUser: {query}"
