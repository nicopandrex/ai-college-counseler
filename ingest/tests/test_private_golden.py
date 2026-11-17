"""M1 done-bar: extraction of the owner's real audit matches the hand-corrected golden.

Runs only where the private fixtures exist (never in CI): the audit PDF, the golden after the
owner's review (`reviewed: true`), and a recorded LLM response under fixtures/private/llm-cache,
which is replayed (no network). Provider/model default to the ones the cassette was recorded with.
"""

import json
import os
from pathlib import Path

import pytest

from planner_ingest.golden import Golden, compare
from planner_ingest.pipeline import PURPOSE, extract_audit
from planner_llm import CacheMode, LLMGateway
from planner_llm.gateway import provider_from_env

PRIVATE = Path(__file__).resolve().parents[2] / "fixtures" / "private"
PDF = PRIVATE / "audit.pdf"
GOLDEN = PRIVATE / "golden" / "audit.golden.json"
CACHE = PRIVATE / "llm-cache"


def _reviewed() -> bool:
    return GOLDEN.exists() and json.loads(GOLDEN.read_text()).get("reviewed") is True


pytestmark = pytest.mark.skipif(
    not (PDF.exists() and _reviewed() and (CACHE / PURPOSE).exists()),
    reason="needs the private audit, an owner-reviewed golden, and a recorded extraction",
)


def test_real_audit_matches_reviewed_golden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", os.environ.get("LLM_PROVIDER", "gemini"))
    monkeypatch.setenv("LLM_API_KEY", os.environ.get("LLM_API_KEY", "replay-only"))
    model = os.environ.get("LLM_MODEL", "gemini-3.5-flash")
    gateway = LLMGateway(provider_from_env(), model, CACHE, CacheMode.REPLAY)
    result = extract_audit(PDF, gateway)
    assert compare(result.audit, Golden.model_validate_json(GOLDEN.read_text())) == []
