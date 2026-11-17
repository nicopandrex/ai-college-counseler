"""The single entry point for LLM calls.

Requests are keyed by a hash of everything that can change the output (provider, model,
prompts, schema, generation settings). In REPLAY mode a missing cassette is an error, so
tests never make network calls and are free to rerun.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


class CacheMode(Enum):
    REPLAY = "replay"  # cache only; a miss raises CacheMiss
    RECORD = "record"  # cache first; a miss calls the provider and stores the response
    LIVE = "live"  # always call the provider; never read or write the cache


class LLMError(RuntimeError):
    """The provider returned something unusable (refusal, truncation, bad JSON)."""


class CacheMiss(LLMError):
    """REPLAY mode found no recorded response for this request."""


@dataclass(frozen=True)
class JsonRequest:
    purpose: str
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int = 64000
    effort: str = "high"


class Provider(Protocol):
    name: str

    def complete_json(self, request: JsonRequest, model: str) -> str:
        """Return the raw JSON text produced for `request`."""
        ...


class LLMGateway:
    def __init__(self, provider: Provider, model: str, cache_dir: Path, mode: CacheMode) -> None:
        self.provider = provider
        self.model = model
        self.cache_dir = cache_dir
        self.mode = mode

    @classmethod
    def from_env(cls, purpose: str = "default") -> LLMGateway:
        """Configure from LLM_PROVIDER, LLM_MODEL[_<PURPOSE>], LLM_API_KEY, LLM_CACHE_MODE/DIR."""
        model = os.environ.get(f"LLM_MODEL_{purpose.upper()}") or os.environ.get("LLM_MODEL", "")
        mode = CacheMode(os.environ.get("LLM_CACHE_MODE", CacheMode.REPLAY.value))
        cache_dir = Path(os.environ.get("LLM_CACHE_DIR", ".llm-cache"))
        return cls(provider_from_env(), model=model, cache_dir=cache_dir, mode=mode)

    def cache_key(self, request: JsonRequest) -> str:
        material = {"provider": self.provider.name, "model": self.model, **asdict(request)}
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def complete_json(self, request: JsonRequest) -> dict[str, Any]:
        path = self.cache_dir / request.purpose / f"{self.cache_key(request)}.json"
        if self.mode is not CacheMode.LIVE and path.exists():
            return _parse(json.loads(path.read_text())["response"])
        if self.mode is CacheMode.REPLAY:
            raise CacheMiss(f"no recorded response for {request.purpose} at {path}")
        if not self.model:
            raise LLMError("LLM_MODEL is not set")

        text = self.provider.complete_json(request, self.model)
        parsed = _parse(text)
        if self.mode is CacheMode.RECORD:
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {"provider": self.provider.name, "model": self.model, "response": text}
            path.write_text(json.dumps(record, indent=1))
        return parsed


def _parse(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"provider returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("provider returned JSON that is not an object")
    return value


def provider_from_env() -> Provider:
    name = os.environ.get("LLM_PROVIDER", "anthropic")
    if name == "anthropic":
        from planner_llm.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=os.environ.get("LLM_API_KEY") or None)
    if name == "gemini":
        from planner_llm.providers.gemini import GeminiProvider

        api_key = os.environ.get("LLM_API_KEY")
        if not api_key:
            raise LLMError("LLM_API_KEY is not set")
        return GeminiProvider(api_key=api_key)
    raise LLMError(f"unsupported LLM_PROVIDER: {name}")
