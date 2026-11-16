from planner_llm import JsonRequest
from planner_llm.providers.anthropic import build_request_kwargs


def test_request_kwargs_use_structured_output_and_fallbacks() -> None:
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    request = JsonRequest(purpose="p", system="SYS", user="USER", schema=schema, effort="high")
    kwargs = build_request_kwargs(request, model="claude-opus-5-5")

    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["system"] == "SYS"
    assert kwargs["messages"] == [{"role": "user", "content": "USER"}]
    assert kwargs["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": schema},
    }
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
