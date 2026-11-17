"""Google Gemini provider via its OpenAI-compatible endpoint (API key as a Bearer token)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from planner_llm.gateway import JsonRequest, LLMError

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
TIMEOUT_SECONDS = 600.0  # long audits at high reasoning effort can take minutes
RETRY_STATUSES = {429, 500, 503}
ATTEMPTS = 4


def build_request_body(request: JsonRequest, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": request.purpose, "schema": request.schema, "strict": True},
        },
        "reasoning_effort": request.effort,
        "max_tokens": request.max_tokens,
    }


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(payload, list) and payload:
        payload = payload[0]
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return str(payload["error"].get("message", payload["error"]))
    return str(payload)[:500]


class GeminiProvider:
    name = "gemini"

    def __init__(
        self, api_key: str, transport: httpx.BaseTransport | None = None, backoff: float = 5.0
    ) -> None:
        self._backoff = backoff
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT_SECONDS,
            transport=transport,
        )

    def complete_json(self, request: JsonRequest, model: str) -> str:
        body = build_request_body(request, model)
        for attempt in range(ATTEMPTS):
            response = self._client.post("/chat/completions", json=body)
            if response.status_code not in RETRY_STATUSES or attempt == ATTEMPTS - 1:
                break
            time.sleep(self._backoff * 2**attempt)
        if response.status_code != 200:
            raise LLMError(f"Gemini API {response.status_code}: {_error_message(response)}")
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LLMError("response truncated at max_tokens")
        content = choice["message"].get("content")
        if not content:
            raise LLMError(
                f"response contained no content (finish_reason={choice.get('finish_reason')})"
            )
        return content
