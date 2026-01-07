from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILES = [
    str(Path(__file__).resolve().parents[1] / ".env"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILES, extra="ignore")

    PROJECT_NAME: str = "Ask HR Router"
    ENV: str = "local"
    PORT: int = 8000

    GOOGLE_PROJECT_ID: str
    GOOGLE_LOCATION: str

    IBM_VERIFY_CLIENT_ID: str = ""
    IBM_VERIFY_ISSUER: str = ""

    RAG_SERVICE_URL: str = "http://localhost:8001"
    WORKDAY_TOOLS_URL: str = "http://localhost:5001"
    WORKDAY_TOOLS_TIMEOUT_SECONDS: int = 300

    ROUTER_MODEL: str = Field(
        default="gemini-2.5-pro",
        validation_alias="ASKHR_ROUTER_MODEL",
    )


settings = Settings()
