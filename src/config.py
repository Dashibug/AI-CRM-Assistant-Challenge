from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    llm_api_url: str = os.getenv("LLM_API_URL", "https://amo-ai-challenge-1.up.railway.app/v1/chat/completions")
    llm_api_key: str = os.getenv("LLM_API_KEY",  "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    timezone: str = os.getenv("TIMEZONE", "Europe/Moscow")
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    request_max_retries: int = int(os.getenv("REQUEST_MAX_RETRIES", "2"))

SETTINGS = Settings()

