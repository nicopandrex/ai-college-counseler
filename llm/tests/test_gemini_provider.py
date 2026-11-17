import httpx
import pytest

from planner_llm import JsonRequest, LLMError
from planner_llm.providers.gemini import GeminiProvider, build_request_body

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def test_request_body_uses_strict_json_schema() -> None:
    request = JsonRequest(purpose="p", system="SYS", user="USER", schema=SCHEMA, effort="high")
    body = build_request_body(request, model="gemini-x")
    assert body["model"] == "gemini-x"
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "p", "schema": SCHEMA, "strict": True},
    }
    assert body["reasoning_effort"] == "high"
    assert body["max_tokens"] == request.max_tokens


def _provider(handler) -> GeminiProvider:
    return GeminiProvider(api_key="k", transport=httpx.MockTransport(handler))


def test_returns_message_content_and_sends_bearer_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer k"
        assert req.url.path.endswith("/openai/chat/completions")
        body = {"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]}
        return httpx.Response(200, json=body)

    request = JsonRequest(purpose="p", system="s", user="u", schema=SCHEMA)
    assert _provider(handler).complete_json(request, "m") == '{"a": 1}'


def test_truncation_is_an_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = {"choices": [{"message": {"content": '{"a"'}, "finish_reason": "length"}]}
        return httpx.Response(200, json=body)

    with pytest.raises(LLMError, match="truncated"):
        _provider(handler).complete_json(JsonRequest("p", "s", "u", SCHEMA), "m")


def test_api_error_message_is_surfaced() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=[{"error": {"code": 429, "message": "quota exceeded"}}])

    with pytest.raises(LLMError, match="quota exceeded"):
        _provider(handler).complete_json(JsonRequest("p", "s", "u", SCHEMA), "m")
