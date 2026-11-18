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
    return GeminiProvider(api_key="k", transport=httpx.MockTransport(handler), backoff=0)


def test_returns_message_content_and_sends_bearer_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer k"
        assert req.url.path.endswith("/openai/chat/completions")
        body = {
            "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 50,
                "completion_tokens_details": {"reasoning_tokens": 30},
            },
        }
        return httpx.Response(200, json=body)

    request = JsonRequest(purpose="p", system="s", user="u", schema=SCHEMA)
    completion = _provider(handler).complete_json(request, "m")
    assert completion.text == '{"a": 1}'
    assert completion.usage == {"input_tokens": 120, "output_tokens": 50, "reasoning_tokens": 30}


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


def test_transient_overload_is_retried_then_succeeds() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, json=[{"error": {"message": "high demand"}}])
        body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        return httpx.Response(200, json=body)

    provider = GeminiProvider(api_key="k", transport=httpx.MockTransport(handler), backoff=0)
    assert provider.complete_json(JsonRequest("p", "s", "u", SCHEMA), "m").text == "{}"
    assert len(calls) == 3


def test_persistent_overload_gives_up() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json=[{"error": {"message": "high demand"}}])

    provider = GeminiProvider(api_key="k", transport=httpx.MockTransport(handler), backoff=0)
    with pytest.raises(LLMError, match="high demand"):
        provider.complete_json(JsonRequest("p", "s", "u", SCHEMA), "m")


def test_dropped_connection_is_retried() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadError("Connection reset by peer")
        body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        return httpx.Response(200, json=body)

    assert _provider(handler).complete_json(JsonRequest("p", "s", "u", SCHEMA), "m").text == "{}"
    assert len(calls) == 2
