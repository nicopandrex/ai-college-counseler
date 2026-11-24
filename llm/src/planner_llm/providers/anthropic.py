"""Anthropic Messages API provider (structured JSON output)."""

from __future__ import annotations

from typing import Any

import anthropic

from planner_llm.gateway import JsonRequest, LLMError

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def build_request_kwargs(request: JsonRequest, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": request.max_tokens,
        "system": request.system,
        "messages": [{"role": "user", "content": request.user}],
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": request.effort,
            "format": {"type": "json_schema", "schema": request.schema},
        },
        # On a safety decline, the API re-runs the request on a fallback model.
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def complete_json(self, request: JsonRequest, model: str) -> str:
        kwargs = build_request_kwargs(request, model)
        with self._client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            raise LLMError(f"model declined the request: {message.stop_details}")
        if message.stop_reason == "max_tokens":
            raise LLMError("response truncated at max_tokens")
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text:
            raise LLMError("response contained no text block")
        return text
