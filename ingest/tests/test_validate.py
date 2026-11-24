import json
from pathlib import Path

import pytest
from synth_degreeworks import Cell, Text, block_header, build_pdf, requirement, sample_audit

from planner_ingest.config import load_school_config
from planner_ingest.extraction import CourseListRule, ExtractedAudit
from planner_ingest.ids import requirement_ids
from planner_ingest.layout import AuditLayout, parse_layout
from planner_ingest.validate import (
    FLAGGED_CONFIDENCE_CAP,
    anchor_requirements,
    finalize,
    review_items,
)

UVM = load_school_config("uvm")
FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_extraction.json"


@pytest.fixture(scope="module")
def layout(tmp_path_factory: pytest.TempPathFactory) -> AuditLayout:
    return parse_layout(sample_audit(tmp_path_factory.mktemp("v") / "a.pdf"), UVM)


@pytest.fixture
def audit() -> ExtractedAudit:
    return ExtractedAudit.model_validate(json.loads(FIXTURE.read_text()))


def by_title(audit: ExtractedAudit, title: str):
    return next(r for r in audit.requirements if r.title == title)


def codes(issues) -> list[str]:
    return sorted(i.code for i in issues)


def test_correct_extraction_has_no_issues(layout: AuditLayout, audit: ExtractedAudit) -> None:
    final, issues = finalize(audit, layout, UVM)
    assert issues == []
    assert by_title(final, "Calculus I").req_id == (
        "bachelor_science_test.choose_one_track.track_1.calculus_i"
    )
    assert by_title(final, "Bachelor of Science, TEST").req_id == "bachelor_science_test"


def test_courses_are_rebuilt_from_document_rows(layout: AuditLayout, audit: ExtractedAudit) -> None:
    final, _ = finalize(audit, layout, UVM)
    db = next(c for c in final.courses_taken if c.code == "CS 2500")
    assert (db.status, db.credits, db.grade) == ("in_progress", 3.0, "IP")
    assert db.applied_to_req_ids == [
        "bachelor_science_test.intermediate_level_3_additional_credits"
    ]
    assert {c.code for c in final.courses_taken} == {"CS 1210", "CS 2500", "MATH 1234", "ARTS 1XXX"}


def test_status_mismatch_with_icon_caps_confidence(
    layout: AuditLayout, audit: ExtractedAudit
) -> None:
    seminar = by_title(audit, "Senior Seminar")
    audit.requirements[audit.requirements.index(seminar)] = seminar.model_copy(
        update={"status": "complete"}
    )
    final, issues = finalize(audit, layout, UVM)
    assert "status_mismatch" in codes(issues)
    assert by_title(final, "Senior Seminar").confidence == FLAGGED_CONFIDENCE_CAP
    assert by_title(final, "Senior Seminar") in review_items(final, issues)


def test_count_unit_confusion_is_caught(layout: AuditLayout, audit: ExtractedAudit) -> None:
    calc2 = by_title(audit, "Calculus II")
    wrong = CourseListRule(kind="course_list", count=4, count_unit="courses", from_=["MATH 1248"])
    audit.requirements[audit.requirements.index(calc2)] = calc2.model_copy(update={"rule": wrong})
    _, issues = finalize(audit, layout, UVM)
    assert codes(issues) == ["count_unit_mismatch"]


def test_missed_row_is_an_error(layout: AuditLayout, audit: ExtractedAudit) -> None:
    audit.requirements.remove(by_title(audit, "Senior Seminar"))
    _, issues = finalize(audit, layout, UVM)
    (issue,) = issues
    assert (issue.code, issue.severity) == ("missing_requirement", "error")


def test_invented_quote_and_course_are_flagged(layout: AuditLayout, audit: ExtractedAudit) -> None:
    cs1 = by_title(audit, "Computer Programming I")
    audit.requirements[audit.requirements.index(cs1)] = cs1.model_copy(
        update={
            "source_quote": "Programming I requirement satisfied",
            "satisfied_by": ["CS 1210", "CS 1100"],
        }
    )
    audit.courses_taken.append(audit.courses_taken[0].model_copy(update={"code": "CS 1100"}))
    _, issues = finalize(audit, layout, UVM)
    assert codes(issues) == ["course_not_in_document", "quote_not_found", "satisfied_by_mismatch"]


def test_course_field_disagreement_is_reported(layout: AuditLayout, audit: ExtractedAudit) -> None:
    audit.courses_taken[2] = audit.courses_taken[2].model_copy(update={"grade": "A"})
    final, issues = finalize(audit, layout, UVM)
    assert codes(issues) == ["course_field_mismatch"]
    assert next(c for c in final.courses_taken if c.code == "MATH 1234").grade == "B+"


def test_complete_requirement_met_only_by_in_progress_work(
    layout: AuditLayout, audit: ExtractedAudit
) -> None:
    req = by_title(audit, "INTERMEDIATE LEVEL. 3 additional credits:")
    audit.requirements[audit.requirements.index(req)] = req.model_copy(
        update={"status": "complete"}
    )
    _, issues = finalize(audit, layout, UVM)
    assert codes(issues) == ["complete_only_in_progress", "status_mismatch"]


def test_malformed_rule_code(layout: AuditLayout, audit: ExtractedAudit) -> None:
    seminar = by_title(audit, "Senior Seminar")
    bad = CourseListRule(
        kind="course_list", count=1, count_unit="courses", from_=["Computer Sci 3920"]
    )
    audit.requirements[audit.requirements.index(seminar)] = seminar.model_copy(update={"rule": bad})
    _, issues = finalize(audit, layout, UVM)
    assert codes(issues) == ["malformed_course_code"]


def test_structural_tags_in_quotes_do_not_misanchor(
    layout: AuditLayout, audit: ExtractedAudit
) -> None:
    block = by_title(audit, "Bachelor of Science, TEST")
    tagged = block.model_copy(update={"source_quote": "BLOCK Bachelor of Science, TEST"})
    audit.requirements[audit.requirements.index(block)] = tagged
    final, issues = finalize(audit, layout, UVM)
    assert issues == []
    assert by_title(final, "Bachelor of Science, TEST").req_id == "bachelor_science_test"


def test_attribute_selector_is_a_valid_rule_code(
    layout: AuditLayout, audit: ExtractedAudit
) -> None:
    seminar = by_title(audit, "Senior Seminar")
    rule = CourseListRule(
        kind="course_list", count=1, count_unit="courses", from_=["@ @ with attribute = WIL1"]
    )
    audit.requirements[audit.requirements.index(seminar)] = seminar.model_copy(
        update={"rule": rule, "has_wildcard": True}
    )
    _, issues = finalize(audit, layout, UVM)
    assert issues == []


def test_unparsed_rule_cannot_claim_high_confidence(
    layout: AuditLayout, audit: ExtractedAudit
) -> None:
    gpa = by_title(audit, "You meet the minimum Overall GPA requirement.")
    audit.requirements[audit.requirements.index(gpa)] = gpa.model_copy(update={"confidence": 0.9})
    final, issues = finalize(audit, layout, UVM)
    assert codes(issues) == ["unparsed_overconfident"]
    gpa_final = by_title(final, "You meet the minimum Overall GPA requirement.")
    assert gpa_final.confidence == FLAGGED_CONFIDENCE_CAP
    # completed (icon-confirmed) and nothing else wrong: reported, but not queued for review
    assert gpa_final not in review_items(final, issues)


def test_listing_block_is_not_a_requirement(layout: AuditLayout, audit: ExtractedAudit) -> None:
    listing = audit.requirements[0].model_copy(
        update={"req_id": "electives", "title": "Electives", "status": "unknown",
                "source_quote": "Electives", "satisfied_by": ["ARTS 1XXX"], "confidence": 0.6}
    )  # fmt: skip
    audit.requirements.append(listing)
    _, issues = finalize(audit, layout, UVM)
    assert codes(issues) == ["listing_not_requirement"]


def test_given_req_id_anchors_exactly_even_with_identical_text(tmp_path: Path) -> None:
    calc = requirement(2, "incomplete", "Calculus I", content=["4 Credits in MATH 1234"])
    legend = Cell(height=30.0, texts=[Text(28.3, 8, "Legend", "Helvetica-Bold", 10)])
    cells = [block_header("Major", "INCOMPLETE", "x"),
             requirement(0, "incomplete", "TRACK A"), calc,
             requirement(0, "incomplete", "TRACK B"), calc, legend]  # fmt: skip
    layout = parse_layout(build_pdf(tmp_path / "t.pdf", [cells]), UVM)
    base = json.loads(FIXTURE.read_text())
    template = next(r for r in base["requirements"] if r["title"] == "Calculus II")

    def entry(req_id: str, title: str, quote: str) -> dict:
        return {**template, "req_id": req_id, "title": title, "source_quote": quote}

    audit = ExtractedAudit.model_validate({**base, "courses_taken": [], "requirements": [
        entry("major", "Major", "Major"),
        entry("major.track_b.calculus_i", "Calculus I", "4 Credits in MATH 1234"),
        entry("major.track_a", "TRACK A", "TRACK A"),
        entry("major.track_b", "TRACK B", "TRACK B"),
        entry("major.track_a.calculus_i", "Calculus I", "4 Credits in MATH 1234"),
    ]})  # fmt: skip
    anchors = anchor_requirements(audit, layout)
    rows = {r.row_id: r for r in layout.rows}
    ids = requirement_ids(layout)
    assert [ids[a.key] for a in anchors] == [r.req_id for r in audit.requirements]
    assert rows[anchors[1].key].parent_id == anchors[3].key  # B's copy, not A's


def test_review_skips_completed_requirements(layout: AuditLayout, audit: ExtractedAudit) -> None:
    final, issues = finalize(audit, layout, UVM)
    gpa = by_title(final, "You meet the minimum Overall GPA requirement.")  # complete, conf 0.6
    seminar = by_title(final, "Senior Seminar").model_copy(update={"confidence": 0.5})
    final.requirements[final.requirements.index(by_title(final, "Senior Seminar"))] = seminar
    items = review_items(final, issues)
    assert gpa not in items
    assert seminar in items
