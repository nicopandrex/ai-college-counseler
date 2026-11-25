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
    doc = DOCS.read_text(encoding="utf-8")
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


class SequenceProvider:
    """Returns one canned response per call, in order."""

    name = "sequence"

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.requests: list[JsonRequest] = []

    def complete_json(self, request: JsonRequest, model: str) -> str:
        self.requests.append(request)
        return self.texts[len(self.requests) - 1]


def test_rendered_input_carries_deterministic_req_ids(tmp_path: Path) -> None:
    layout = parse_layout(sample_audit(tmp_path / "a.pdf"), load_school_config("uvm"))
    user = extraction_request(layout).user
    assert "BLOCK [req_id: bachelor_science_test] Bachelor of Science, TEST" in user
    assert "[req_id: bachelor_science_test.choose_one_track.track_1.calculus_i]" in user
    assert "[req_id: electives]" not in user  # listing blocks are not requirements


def test_omitted_requirements_are_requested_again(tmp_path: Path) -> None:
    pdf = sample_audit(tmp_path / "audit.pdf")
    full = json.loads(FIXTURE.read_text())
    seminar = next(r for r in full["requirements"] if r["title"] == "Senior Seminar")
    first = {**full, "requirements": [r for r in full["requirements"] if r is not seminar]}
    seminar = {**seminar, "req_id": "bachelor_science_test.senior_seminar"}
    second = {**full, "courses_taken": [], "requirements": [seminar]}
    provider = SequenceProvider([json.dumps(first), json.dumps(second)])
    gateway = LLMGateway(provider, "m", tmp_path / "c", CacheMode.LIVE)

    result = extract_audit(pdf, gateway)
    assert result.issues == []
    assert len(provider.requests) == 2
    assert "bachelor_science_test.senior_seminar" in provider.requests[1].user
    ids = [r.req_id for r in result.audit.requirements]
    assert ids.count("bachelor_science_test.senior_seminar") == 1
