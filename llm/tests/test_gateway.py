import json
from pathlib import Path

import pytest

from planner_llm import CacheMiss, CacheMode, JsonRequest, LLMError, LLMGateway

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
