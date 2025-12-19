import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent import chat_with_workday, get_workday_id, reset_auth_cache
from doc_generator import (
    get_document_filename_from_cache,
    get_document_from_cache,
    get_document_mimetype_from_cache,
)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI()

if str(os.getenv("ASKHR_RESET_AUTH_ON_STARTUP", "true")).lower() in ("1", "true", "yes"):
    reset_auth_cache()


@app.get("/")
async def index(request: Request):
    """Serve the main HTML interface."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Return empty favicon to avoid 404 noise."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/chat")
async def chat(request: Request) -> Dict[str, Any]:
    """Handle chat messages."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No JSON body provided",
        )

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No JSON body provided",
        )

    message = str(data.get("message", "")).strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No message provided",
        )

    try:
        response = chat_with_workday(message)
        return {"response": response}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation error: {e}",
        )
    except TimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Request timeout: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Server error: {e}",
        )


@app.get("/diagnostics")
async def diagnostics() -> Dict[str, Any]:
    """Return diagnostic info about Workday auth and user data."""
    try:
        data_json = get_workday_id()
        return {"data": data_json}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.post("/reset")
async def reset() -> Dict[str, Any]:
    """Clear cached auth so next request prompts login again."""
    try:
        ok = reset_auth_cache()
        return {"success": ok, "message": "Auth cache cleared. Next request will trigger login."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get("/download_doc/{doc_key}")
async def download_doc_from_memory(doc_key: str):
    """Download a document from memory cache."""
    doc_bytes = get_document_from_cache(doc_key)
    if doc_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or expired",
        )

    filename = get_document_filename_from_cache(doc_key) or "document.docx"
    mimetype = get_document_mimetype_from_cache(doc_key) or "application/octet-stream"

    doc_bytes.seek(0)
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return StreamingResponse(doc_bytes, media_type=mimetype, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "Not found"})
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "Invalid request", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=5000, reload=False)
