import json
from pathlib import Path

import pytest
from synth_degreeworks import sample_audit

from planner_ingest.config import load_school_config
from planner_ingest.layout import parse_layout
from planner_ingest.pipeline import extract_audit, extraction_request
from planner_ingest.prompts.loader import extraction_system_prompt
from planner_llm import CacheMiss, CacheMode, JsonRequest, LLMError, LLMGateway

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_extraction.json"
DOCS = Path(__file__).resolve().parents[2] / "docs" / "audit-extraction-prompt.md"


class StubProvider:
    name = "stub"

    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[JsonRequest] = []

    def complete_json(self, request: JsonRequest, model: str) -> str:
        self.requests.append(request)
        return self.text


def test_packaged_prompt_matches_docs_verbatim() -> None:
    doc = DOCS.read_text()
    body = doc[doc.index("\n---\n") + 5 : doc.index("\n---\n\n# Downstream")].strip()
    assert extraction_system_prompt().startswith(body + "\n")


def test_end_to_end_with_record_then_replay(tmp_path: Path) -> None:
    pdf = sample_audit(tmp_path / "audit.pdf")
    provider = StubProvider(FIXTURE.read_text())
    recorder = LLMGateway(provider, "model-x", tmp_path / "cache", CacheMode.RECORD)
    first = extract_audit(pdf, recorder)
    assert first.issues == []

    replayer = LLMGateway(StubProvider("unused"), "model-x", tmp_path / "cache", CacheMode.REPLAY)
    second = extract_audit(pdf, replayer)
    assert second.report() == first.report()
    assert "Example" not in provider.requests[0].user  # student name never sent


def test_replay_without_cassette_fails_loudly(tmp_path: Path) -> None:
    pdf = sample_audit(tmp_path / "audit.pdf")
    gateway = LLMGateway(StubProvider("{}"), "m", tmp_path / "cache", CacheMode.REPLAY)
    with pytest.raises(CacheMiss):
        extract_audit(pdf, gateway)


def test_schema_violation_is_an_llm_error(tmp_path: Path) -> None:
    pdf = sample_audit(tmp_path / "audit.pdf")
    broken = json.loads(FIXTURE.read_text())
    broken["requirements"][0]["status"] = "done"
    gateway = LLMGateway(StubProvider(json.dumps(broken)), "m", tmp_path / "c", CacheMode.LIVE)
    with pytest.raises(LLMError):
        extract_audit(pdf, gateway)


def test_request_is_structured_and_strict(tmp_path: Path) -> None:
    layout = parse_layout(sample_audit(tmp_path / "a.pdf"), load_school_config("uvm"))
    request = extraction_request(layout)
    assert request.schema["additionalProperties"] is False
    assert "rule_0" in request.schema["$defs"]
    assert request.user.startswith("AUDIT SUMMARY")
