"""M1 done-bar: extraction of the owner's real audit matches the hand-corrected golden.

Runs only where the private fixtures exist (never in CI): the audit PDF, the reviewed golden,
and a recorded LLM response under fixtures/private/llm-cache (replayed, no network).
"""

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
MODEL = "claude-opus-5-5"

pytestmark = pytest.mark.skipif(
    not (PDF.exists() and GOLDEN.exists() and (CACHE / PURPOSE).exists()),
    reason="private audit, golden or recorded extraction not present",
)


def test_real_audit_matches_reviewed_golden() -> None:
    golden = Golden.model_validate_json(GOLDEN.read_text())
    assert golden.reviewed, "golden is still a draft: hand-correct it and set reviewed=true"
    gateway = LLMGateway(provider_from_env(), MODEL, CACHE, CacheMode.REPLAY)
    result = extract_audit(PDF, gateway)
    assert compare(result.audit, golden) == []
