from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Ask HR Agent"
    ENV: str = "local"
    PORT: int = 8000

    GOOGLE_PROJECT_ID: str
    GOOGLE_LOCATION: str
    RAG_CORPUS_NAME: str
    ASKHR_RAG_MODEL: str = "gemini-2.5-pro"

    IBM_VERIFY_CLIENT_ID: str = ""
    IBM_VERIFY_ISSUER: str = ""

    WORKDAY_API_URL: str = "https://workday.example.com"
    WORKDAY_TOOLS_URL: str = "http://localhost:5000"
    WORKDAY_TOOLS_TIMEOUT_SECONDS: int = 300


settings = Settings()
