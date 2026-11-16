import json
from pathlib import Path

import pytest
from synth_degreeworks import sample_audit

from planner_ingest.config import load_school_config
from planner_ingest.extraction import ExtractedAudit
from planner_ingest.golden import Golden, compare, draft_golden
from planner_ingest.layout import parse_layout
from planner_ingest.validate import finalize

UVM = load_school_config("uvm")
FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_extraction.json"


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory):
    layout = parse_layout(sample_audit(tmp_path_factory.mktemp("g") / "a.pdf"), UVM)
    audit = ExtractedAudit.model_validate(json.loads(FIXTURE.read_text()))
    final, _ = finalize(audit, layout, UVM)
    return layout, final


def test_draft_golden_reads_units_from_document_text(setup) -> None:
    layout, _ = setup
    golden = draft_golden(layout, UVM)
    units = {r.title: r.count_unit for r in golden.requirements}
    assert units["Senior Seminar"] == "courses"  # "Still needed: 1 Class in CS 3920"
    assert units["Calculus II"] == "credits"  # "4 Credits in MATH 1248"
    assert units["Total Credit Requirement"] == "credits"
    assert units["CHOOSE ONE TRACK:"] is None
    assert golden.reviewed is False
    assert {c.code for c in golden.courses} == {"CS 1210", "CS 2500", "MATH 1234", "ARTS 1XXX"}


def test_correct_extraction_matches_draft_except_extras(setup) -> None:
    layout, final = setup
    diffs = compare(final, draft_golden(layout, UVM))
    assert diffs == ["unexpected requirement electives"]


def test_compare_reports_status_unit_and_course_differences(setup) -> None:
    layout, final = setup
    golden = draft_golden(layout, UVM)
    seminar = next(r for r in golden.requirements if r.title == "Senior Seminar")
    seminar.status, seminar.count_unit = "complete", "credits"
    golden.courses[0].grade = "B"
    diffs = compare(final, golden)
    rid = seminar.req_id
    assert f"{rid}: status 'incomplete' != 'complete'" in diffs
    assert f"{rid}: count_unit 'courses' != 'credits'" in diffs
    assert any("grade 'A' != 'B'" in d for d in diffs)


def test_golden_round_trips_json(setup) -> None:
    layout, _ = setup
    golden = draft_golden(layout, UVM)
    assert Golden.model_validate_json(golden.model_dump_json()) == golden
