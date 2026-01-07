import logging
from typing import Any, List

import httpx

from app.models.dto import ChatResponse
from app.services.rag_answer import RagAnswerAgent

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._answer_agent = RagAnswerAgent()

    async def query(self, message: str, session_id: str, user_id: str) -> ChatResponse:
        url = f"{self.base_url}/api/v1/rag/retrieve"
        payload = {"query": message}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                logger.error("RAG service error %s: %s", resp.status_code, resp.text)
                return ChatResponse(
                    reply_text="RAG service is unavailable right now. Please try again.",
                    metadata={"agent": "rag", "error": "service_error"},
                )
            data = resp.json()
            contexts = self._normalize_contexts(data.get("contexts"))
            citations = self._normalize_citations(data.get("citations"))

            if not contexts:
                return ChatResponse(
                    reply_text="I cannot find the information in the provided documents.",
                    citations=citations,
                    metadata={"agent": "rag"},
                )

            reply_text = await self._answer_agent.answer(message, contexts, user_id, session_id)
            if not reply_text:
                reply_text = "I cannot find the information in the provided documents."

            return ChatResponse(
                reply_text=reply_text,
                citations=citations,
                metadata={"agent": "rag"},
            )
        except Exception as exc:
            logger.error("RAG service call failed: %s", exc)
            return ChatResponse(
                reply_text="RAG service is unavailable right now. Please try again.",
                metadata={"agent": "rag", "error": "exception"},
            )

    @staticmethod
    def _normalize_contexts(contexts: Any) -> List[str]:
        if not contexts:
            return []
        if isinstance(contexts, list):
            return [str(item) for item in contexts if item]
        if isinstance(contexts, dict):
            return [str(item) for item in contexts.values() if item]
        if isinstance(contexts, str):
            return [contexts]
        return []

    @staticmethod
    def _normalize_citations(citations: Any) -> List[dict]:
        if not citations:
            return []
        if isinstance(citations, list):
            return [item for item in citations if isinstance(item, dict)]
        if isinstance(citations, dict):
            return [citations]
        return []
