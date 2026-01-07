import logging

from fastapi import APIRouter, HTTPException

from app.models.dto import ChatResponse, RagQuery, RagRetrieveRequest, RagRetrieveResponse, Citation
from app.services.orchestrator import RagAgent

router = APIRouter()
logger = logging.getLogger(__name__)
rag_service = RagAgent()


@router.post("/query", response_model=ChatResponse)
async def rag_query(message: RagQuery):
    try:
        return await rag_service.answer(message.content, message.user_id, message.session_id)
    except Exception as e:
        logger.exception("RAG query failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrieve", response_model=RagRetrieveResponse)
async def retrieve_context(request: RagRetrieveRequest):
    try:
        result = await rag_service.rag_retrieve(request.query)
        contexts = result.get("contexts") or []
        if isinstance(contexts, dict):
            contexts = list(contexts.values())
        elif isinstance(contexts, str):
            contexts = [contexts]

        raw_citations = result.get("citations") or []
        citations = []
        for item in raw_citations:
            if isinstance(item, dict):
                citations.append(Citation(**item))
        return RagRetrieveResponse(contexts=contexts, citations=citations)
    except Exception as e:
        logger.exception("RAG retrieve failed")
        raise HTTPException(status_code=500, detail=str(e))
