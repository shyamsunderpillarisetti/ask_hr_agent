import asyncio
import logging
import time
from pathlib import Path

import requests
from requests import exceptions as request_exceptions

from app.config import settings
from app.models.dto import ChatResponse

logger = logging.getLogger(__name__)


class WorkdayToolsService:
    """Proxy to the Workday Tools agent (external service)."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._token_cache_path = Path(__file__).resolve().parents[3] / "workday_tools" / ".token_cache.json"

    def _wait_for_token_cache(self, deadline: float, interval_seconds: float = 2.0) -> bool:
        while time.time() < deadline:
            if self._token_cache_path.exists():
                return True
            time.sleep(interval_seconds)
        return False

    async def chat(self, message: str) -> ChatResponse:
        url = f"{self.base_url}/chat"

        def _post():
            deadline = time.time() + settings.WORKDAY_TOOLS_TIMEOUT_SECONDS
            attempts = 0

            while True:
                remaining = max(1, int(deadline - time.time()))
                try:
                    resp = requests.post(
                        url,
                        json={"message": message},
                        timeout=remaining,
                    )
                    if resp.ok:
                        data = resp.json()
                        reply = data.get("response") or data.get("message") or str(data)
                        return ChatResponse(reply_text=reply, metadata={"agent": "workday_tools"})

                    error_detail = None
                    try:
                        error_data = resp.json()
                        error_detail = error_data.get("detail") or error_data
                    except Exception:
                        error_detail = resp.text

                    raise request_exceptions.HTTPError(
                        f"Workday tools error {resp.status_code}: {error_detail}"
                    )
                except request_exceptions.Timeout as e:
                    logger.warning("Workday tools timeout: %s", e)
                except Exception as e:
                    logger.error("Workday tools call failed: %s", e)

                if attempts >= 1 or time.time() >= deadline:
                    break

                if not self._token_cache_path.exists():
                    if not self._wait_for_token_cache(deadline):
                        break
                else:
                    time.sleep(2)

                attempts += 1

            return ChatResponse(
                reply_text="Workday login may still be in progress. Please finish the browser login and try again.",
                metadata={"agent": "workday_tools", "error": "retry_exhausted"},
            )

        return await asyncio.to_thread(_post)
