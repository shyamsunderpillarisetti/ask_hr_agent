import asyncio
import logging
import os
from typing import Any, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """You are the AskHR agent for Michaels.

Use only the provided context to answer the question.
If the context does not contain the answer, say: "I cannot find the information in the provided documents."
"""


class RagAnswerAgent:
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
        )
        self._vertex_initialized = True

    def _build_agent(self):
        return self._LlmAgent(
            name="ask_hr_rag_answer",
            model=self._Gemini(model=settings.ROUTER_MODEL),
            instruction=SYSTEM_INSTRUCTION,
            generate_content_config=self._types.GenerateContentConfig(temperature=0.2),
        )

    def _ensure_agent(self) -> None:
        if self._agent is None:
            self._agent = self._build_agent()
            self._runner = self._InMemoryRunner(self._agent, app_name="ask_hr_rag_answer")

    async def answer(self, query: str, contexts: List[str], user_id: str, session_id: str) -> str:
        self._ensure_vertex_init()
        self._ensure_agent()
        safe_user_id = user_id or "anonymous"
        await self._ensure_session(safe_user_id, session_id)
        context_block = "\n\n".join(contexts)
        prompt = f"Question:\n{query}\n\nContext:\n{context_block}"
        content = self._types.Content(
            role="user",
            parts=[self._types.Part.from_text(text=prompt)],
        )

        reply_text = ""
        async for event in self._runner.run_async(
            user_id=safe_user_id,
            session_id=session_id,
            new_message=content,
        ):
            if event.is_final_response():
                reply_text = self._extract_text(event.content) or reply_text
                if event.error_message:
                    reply_text = event.error_message

        return reply_text

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
