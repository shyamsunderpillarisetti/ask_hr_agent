import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.tls import configure_tls


class _GenaiNonTextWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "non-text parts in the response" not in record.getMessage()

configure_tls()
logging.getLogger("google.genai.types").addFilter(_GenaiNonTextWarningFilter())

from app.routers import chat

app = FastAPI(title=settings.PROJECT_NAME)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(chat.router, prefix="/api/v1/rag", tags=["rag"])

@app.get("/health")
def health_check():
    return {"status": "healthy", "env": settings.ENV}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
