from typing import Dict, List, Optional
import asyncio
import logging
import os

from google.adk.agents import LlmAgent
from google.adk.dependencies import vertexai as adk_vertexai
from google.adk.models import Gemini
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.config import settings
from app.models.dto import ChatResponse, Citation


logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """You are the AskHR agent for Michaels.

Always call rag_retrieve first.
Answer only using the returned contexts.
If no context is returned, say you cannot find the information in the provided documents.
"""


class RagAgent:
    def __init__(self):
        self._vertex_initialized = False
        self._ensure_vertex_env()
        self._agent = self._build_agent()
        self._runner = InMemoryRunner(self._agent, app_name="ask_hr_rag")

    def _ensure_vertex_env(self) -> None:
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.GOOGLE_PROJECT_ID)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.GOOGLE_LOCATION)

    def _ensure_vertex_init(self) -> None:
        if self._vertex_initialized:
            return
        adk_vertexai.vertexai.init(
            project=settings.GOOGLE_PROJECT_ID,
            location=settings.GOOGLE_LOCATION,
            api_transport="rest",
        )
        self._vertex_initialized = True

    def _build_agent(self) -> LlmAgent:
        model_name = settings.ASKHR_RAG_MODEL
        return LlmAgent(
            name="ask_hr_rag",
            model=Gemini(model=model_name),
            instruction=SYSTEM_INSTRUCTION,
            tools=[self.rag_retrieve],
            generate_content_config=types.GenerateContentConfig(temperature=0.2),
        )

    async def rag_retrieve(self, query: str) -> Dict[str, List[Dict]]:
        """Retrieve policy/benefits context from Vertex AI RAG."""
        self._ensure_vertex_init()

        def _query():
            return adk_vertexai.rag.retrieval_query(
                text=query,
                rag_corpora=[settings.RAG_CORPUS_NAME],
                similarity_top_k=3,
            )

        try:
            response = await asyncio.to_thread(_query)
        except Exception as exc:
            logger.error("RAG retrieval failed: %s", exc)
            return {"contexts": [], "citations": []}

        contexts: List[str] = []
        citations: List[Dict] = []
        if response and response.contexts and response.contexts.contexts:
            for context in response.contexts.contexts:
                snippet = getattr(context, "text", None)
                contexts.append(snippet or "")
                citations.append({
                    "title": getattr(context, "source_display_name", None) or "Document",
                    "url": getattr(context, "source_uri", None),
                    "snippet": snippet,
                    "confidence": getattr(context, "score", None),
                })

        return {"contexts": contexts, "citations": citations}

    async def answer(self, query: str, user_id: str, session_id: str) -> ChatResponse:
        safe_user_id = user_id or "anonymous"
        await self._ensure_session(safe_user_id, session_id)
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=query)],
        )

        reply_text = ""
        citations: List[Citation] = []
        metadata: Dict[str, str] = {"agent": "rag"}

        async for event in self._runner.run_async(
            user_id=safe_user_id,
            session_id=session_id,
            new_message=content,
        ):
            for function_response in event.get_function_responses():
                tool_name = function_response.name or ""
                payload = function_response.response or {}
                if isinstance(payload, dict) and "output" in payload and isinstance(payload["output"], dict):
                    payload = payload["output"]

                if tool_name == "rag_retrieve":
                    citations = self._parse_citations(payload)

            if event.is_final_response():
                reply_text = self._extract_text(event.content) or reply_text
                if event.error_message:
                    reply_text = event.error_message

        if not reply_text:
            reply_text = "I couldn't generate a response. Please try again."

        return ChatResponse(reply_text=reply_text, citations=citations, metadata=metadata)

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
    def _extract_text(content: Optional[types.Content]) -> str:
        if not content or not content.parts:
            return ""
        return "".join(
            part.text for part in content.parts if part.text and not getattr(part, "thought", False)
        )

    @staticmethod
    def _parse_citations(payload: Dict) -> List[Citation]:
        citations: List[Citation] = []
        for item in payload.get("citations", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            citations.append(Citation(
                title=item.get("title") or "Document",
                url=item.get("url"),
                snippet=item.get("snippet"),
                confidence=item.get("confidence"),
            ))
        return citations
