"""The single entry point for LLM calls.

Requests are keyed by a hash of everything that can change the output (provider, model,
prompts, schema, generation settings). In REPLAY mode a missing cassette is an error, so
tests never make network calls and are free to rerun.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
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


class LLMBudgetError(LLMError):
    """The run hit its live-call limit (LLM_MAX_LIVE_CALLS); raise it explicitly for big jobs."""


DEFAULT_MODEL = "gemini-3.5-flash"  # cheap by default; stronger models only when chosen
# Measured exception (PROGRESS.md): Flash drops enrollment restrictions from prerequisite
# notes. Prerequisite parsing is one-off per changed note (answer store), so Pro stays cheap.
DEFAULT_MODELS = {"prereq_parse": "gemini-3.1-pro-preview"}
DEFAULT_MAX_LIVE_CALLS = 30
USAGE_KEYS = ("input_tokens", "output_tokens", "reasoning_tokens")


@dataclass(frozen=True)
class JsonRequest:
    purpose: str
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int = 64000
    effort: str = "high"


@dataclass(frozen=True)
class Completion:
    text: str
    usage: dict[str, int]  # input_tokens, output_tokens (incl. reasoning), reasoning_tokens


class Provider(Protocol):
    name: str

    def complete_json(self, request: JsonRequest, model: str) -> str | Completion:
        """Return the raw JSON text produced for `request` (with token usage if known)."""
        ...


class LLMGateway:
    def __init__(
        self,
        provider: Provider,
        model: str,
        cache_dir: Path,
        mode: CacheMode,
        max_live_calls: int | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.cache_dir = cache_dir
        self.mode = mode
        self.max_live_calls = max_live_calls
        self.usage = {"live_calls": 0, **dict.fromkeys(USAGE_KEYS, 0)}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, purpose: str = "default") -> LLMGateway:
        """Configure from LLM_PROVIDER, LLM_MODEL[_<PURPOSE>], LLM_API_KEY, LLM_CACHE_MODE/DIR,
        LLM_MAX_LIVE_CALLS (0 = unlimited)."""
        model = (
            os.environ.get(f"LLM_MODEL_{purpose.upper()}")
            or os.environ.get("LLM_MODEL")
            or DEFAULT_MODELS.get(purpose, DEFAULT_MODEL)
        )
        mode = CacheMode(os.environ.get("LLM_CACHE_MODE", CacheMode.REPLAY.value))
        cache_dir = Path(os.environ.get("LLM_CACHE_DIR", ".llm-cache"))
        budget = int(os.environ.get("LLM_MAX_LIVE_CALLS", DEFAULT_MAX_LIVE_CALLS))
        return cls(
            provider_from_env(),
            model=model,
            cache_dir=cache_dir,
            mode=mode,
            max_live_calls=budget or None,
        )

    def usage_summary(self) -> str:
        u = self.usage
        return (
            f"LLM ({self.model}): {u['live_calls']} live calls, {u['input_tokens']:,} input + "
            f"{u['output_tokens']:,} output tokens ({u['reasoning_tokens']:,} of them thinking)"
        )

    def cache_key(self, request: JsonRequest) -> str:
        material = {"provider": self.provider.name, "model": self.model, **asdict(request)}
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def complete_json(self, request: JsonRequest) -> dict[str, Any]:
        path = self.cache_dir / request.purpose / f"{self.cache_key(request)}.json"
        if self.mode is not CacheMode.LIVE and path.exists():
            return _parse(json.loads(path.read_text(encoding="utf-8"))["response"])
        if self.mode is CacheMode.REPLAY:
            raise CacheMiss(f"no recorded response for {request.purpose} at {path}")
        if not self.model:
            raise LLMError("LLM_MODEL is not set")

        with self._lock:
            if self.max_live_calls is not None and self.usage["live_calls"] >= self.max_live_calls:
                raise LLMBudgetError(
                    f"live-call limit of {self.max_live_calls} reached; raise LLM_MAX_LIVE_CALLS "
                    "for a deliberate bulk job"
                )
            self.usage["live_calls"] += 1
        result = self.provider.complete_json(request, self.model)
        completion = result if isinstance(result, Completion) else Completion(result, {})
        with self._lock:
            for key in USAGE_KEYS:
                self.usage[key] += completion.usage.get(key, 0)
        parsed = _parse(completion.text)
        if self.mode is CacheMode.RECORD:
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "provider": self.provider.name,
                "model": self.model,
                "response": completion.text,
                "usage": completion.usage,
            }
            path.write_text(json.dumps(record, indent=1), encoding="utf-8")
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
