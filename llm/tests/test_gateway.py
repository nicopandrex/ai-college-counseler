import json
from pathlib import Path

import pytest

from planner_llm import (
    CacheMiss,
    CacheMode,
    Completion,
    JsonRequest,
    LLMBudgetError,
    LLMError,
    LLMGateway,
)
from planner_llm.gateway import DEFAULT_MAX_LIVE_CALLS, DEFAULT_MODEL

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class FakeProvider:
    name = "fake"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def complete_json(self, request: JsonRequest, model: str) -> str:
        self.calls += 1
        return json.dumps(self.payload)


def make_request(user: str = "hello") -> JsonRequest:
    return JsonRequest(purpose="test", system="sys", user=user, schema=SCHEMA)


def test_record_then_replay_hits_cache(tmp_path: Path) -> None:
    provider = FakeProvider({"answer": "42"})
    recorder = LLMGateway(provider, model="m1", cache_dir=tmp_path, mode=CacheMode.RECORD)
    assert recorder.complete_json(make_request()) == {"answer": "42"}
    assert provider.calls == 1

    # Recording again with an identical request is served from the cache.
    assert recorder.complete_json(make_request()) == {"answer": "42"}
    assert provider.calls == 1

    silent = FakeProvider({"answer": "never called"})
    replayer = LLMGateway(silent, model="m1", cache_dir=tmp_path, mode=CacheMode.REPLAY)
    assert replayer.complete_json(make_request()) == {"answer": "42"}
    assert silent.calls == 0


def test_replay_miss_raises_instead_of_calling(tmp_path: Path) -> None:
    provider = FakeProvider({"answer": "x"})
    gateway = LLMGateway(provider, model="m1", cache_dir=tmp_path, mode=CacheMode.REPLAY)
    with pytest.raises(CacheMiss):
        gateway.complete_json(make_request())
    assert provider.calls == 0


def test_cache_key_covers_model_and_prompt(tmp_path: Path) -> None:
    provider = FakeProvider({"answer": "x"})
    LLMGateway(provider, model="m1", cache_dir=tmp_path, mode=CacheMode.RECORD).complete_json(
        make_request("a")
    )
    replay_other_model = LLMGateway(provider, model="m2", cache_dir=tmp_path, mode=CacheMode.REPLAY)
    with pytest.raises(CacheMiss):
        replay_other_model.complete_json(make_request("a"))
    replay_other_prompt = LLMGateway(
        provider, model="m1", cache_dir=tmp_path, mode=CacheMode.REPLAY
    )
    with pytest.raises(CacheMiss):
        replay_other_prompt.complete_json(make_request("b"))


def test_live_mode_never_writes_cache(tmp_path: Path) -> None:
    provider = FakeProvider({"answer": "x"})
    gateway = LLMGateway(provider, model="m1", cache_dir=tmp_path, mode=CacheMode.LIVE)
    gateway.complete_json(make_request())
    gateway.complete_json(make_request())
    assert provider.calls == 2
    assert not any(tmp_path.rglob("*.json"))


def test_non_json_response_is_an_error(tmp_path: Path) -> None:
    class Broken:
        name = "broken"

        def complete_json(self, request: JsonRequest, model: str) -> str:
            return "not json"

    gateway = LLMGateway(Broken(), model="m1", cache_dir=tmp_path, mode=CacheMode.LIVE)
    with pytest.raises(LLMError):
        gateway.complete_json(make_request())


def test_from_env_defaults_to_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_CACHE_MODE", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "some-model")
    gateway = LLMGateway.from_env()
    assert gateway.mode is CacheMode.REPLAY
    assert gateway.model == "some-model"


def test_from_env_purpose_specific_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "default-model")
    monkeypatch.setenv("LLM_MODEL_CHAT", "cheap-model")
    assert LLMGateway.from_env(purpose="chat").model == "cheap-model"
    assert LLMGateway.from_env(purpose="audit_extraction").model == "default-model"


class MeteredProvider(FakeProvider):
    def complete_json(self, request: JsonRequest, model: str) -> Completion:
        self.calls += 1
        return Completion(
            json.dumps(self.payload),
            {"input_tokens": 100, "output_tokens": 40, "reasoning_tokens": 25},
        )


def test_usage_is_recorded_and_totalled(tmp_path: Path) -> None:
    gateway = LLMGateway(MeteredProvider({"answer": "x"}), "m1", tmp_path, CacheMode.RECORD)
    gateway.complete_json(make_request("a"))
    gateway.complete_json(make_request("b"))
    gateway.complete_json(make_request("a"))  # cached: costs nothing
    assert gateway.usage == {
        "live_calls": 2,
        "input_tokens": 200,
        "output_tokens": 80,
        "reasoning_tokens": 50,
    }
    cassette = json.loads(next((tmp_path / "test").glob("*.json")).read_text())
    assert cassette["usage"]["output_tokens"] == 40


def test_live_call_budget_stops_runaway_jobs(tmp_path: Path) -> None:
    provider = FakeProvider({"answer": "x"})
    gateway = LLMGateway(provider, "m1", tmp_path, CacheMode.RECORD, max_live_calls=2)
    gateway.complete_json(make_request("a"))
    gateway.complete_json(make_request("b"))
    with pytest.raises(LLMBudgetError):
        gateway.complete_json(make_request("c"))
    assert provider.calls == 2
    assert gateway.complete_json(make_request("a")) == {"answer": "x"}  # replays stay free


def test_from_env_defaults_to_the_cheap_model_and_a_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_MAX_LIVE_CALLS", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    gateway = LLMGateway.from_env()
    assert gateway.model == DEFAULT_MODEL and gateway.max_live_calls == DEFAULT_MAX_LIVE_CALLS
