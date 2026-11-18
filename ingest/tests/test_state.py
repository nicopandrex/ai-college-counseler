"""derive_state: pure, deterministic, no LLM. Synthetic student only."""

from typing import Any

import pytest

from planner_ingest.extraction import ExtractedAudit
from planner_ingest.state import Assumptions, derive_state


def course(code: str, status: str, credits: float = 3, grade: str = "A", term: str = "Fall 2025"):
    grade = {"in_progress": "IP", "preregistered": "REG"}.get(status, grade)
    return {
        "code": code,
        "title": None,
        "credits": credits,
        "grade": grade,
        "term": term,
        "status": status,
        "applied_to_req_ids": [],
        "source_quote": code,
    }


def req(
    req_id: str,
    status: str,
    satisfied_by=(),
    rule: dict[str, Any] | None = None,
    still_needed: str | None = None,
    title: str | None = None,
):
    return {
        "req_id": req_id,
        "title": title or req_id,
        "program": None,
        "status": status,
        "rule": rule or {"kind": "unparsed", "text": "x"},
        "still_needed_text": still_needed,
        "satisfied_by": list(satisfied_by),
        "has_wildcard": False,
        "confidence": 0.9,
        "source_quote": req_id,
    }


ANY_OF = {"kind": "any_of", "items": [{"kind": "unparsed", "text": "track"}]}


@pytest.fixture
def audit() -> ExtractedAudit:
    return ExtractedAudit.model_validate(
        {
            "student": {
                "catalog_year": "2024-2025",
                "programs": [],
                "class_standing": None,
                "overall_credits_earned": None,
                "overall_credits_in_progress": None,
                "overall_gpa": None,
            },
            "courses_taken": [
                course("CS 1210", "complete"),
                course("CS 2100", "complete", credits=4),
                course("CS 3240", "in_progress", term="Fall 2026"),
                course("MATH 2522", "in_progress", term="Fall 2026"),
                course("CS 3920", "preregistered", term="Spring 2027"),
                course("CHIN 2100", "complete", credits=4),
            ],
            "courses_not_used": [],
            "requirements": [
                req("major", "incomplete"),
                req("major.cs1", "complete", ["CS 1210"]),
                req("major.algorithms", "in_progress", ["CS 3240"]),
                req("major.total", "in_progress", ["CS 1210", "CS 2100", "CS 3240"]),
                req("major.seminar", "incomplete", still_needed="Still needed: 1 Class in CS 3920"),
                req(
                    "major.linear_algebra",
                    "in_progress",
                    ["MATH 2522"],
                    title="Linear Algebra: C or better in MATH 2522",
                ),
                req("chinese", "incomplete"),
                req("chinese.tracks", "incomplete", rule=ANY_OF),
                req("chinese.tracks.track_1", "incomplete"),
                req("chinese.tracks.track_1.chin_1100", "incomplete"),
                req("chinese.tracks.track_2", "incomplete"),
                req("chinese.tracks.track_2.chin_2100", "complete", ["CHIN 2100"]),
                req("chinese.tracks.track_2.chin_4200", "incomplete"),
            ],
            "exceptions": [],
            "parse_notes": [],
        }
    )


def states(state) -> dict[str, str]:
    return {r.req_id: r.state for r in state.requirements}


def test_default_assume_pass_counts_in_progress(audit: ExtractedAudit) -> None:
    state = derive_state(audit)
    s = states(state)
    assert s["major.cs1"] == "satisfied"
    assert s["major.algorithms"] == "provisionally_satisfied"
    assert s["major.total"] == "provisionally_satisfied"
    assert s["major.seminar"] == "open"
    assert "CS 3240" in state.counted_courses  # satisfies prerequisites in plan mode


def test_credit_totals_track_earned_and_in_progress_separately(audit: ExtractedAudit) -> None:
    credits = derive_state(audit).credits
    assert credits.earned == 11  # current standing: completed work only
    assert credits.earned_plus_in_progress == 17  # plan mode: + CS 3240, MATH 2522
    assert credits.preregistered == 3  # never in current standing


def test_preregistered_courses_are_unplannable(audit: ExtractedAudit) -> None:
    state = derive_state(audit)
    assert {"CS 3920", "CS 1210", "CS 3240"} <= state.unplannable_courses
    assert "CS 3920" in state.counted_courses  # plan mode treats it like in-progress


def test_min_grade_requirement_met_by_in_progress_is_tagged(audit: ExtractedAudit) -> None:
    by_id = {r.req_id: r for r in derive_state(audit).requirements}
    assert by_id["major.linear_algebra"].pending_grade_risk is True
    assert by_id["major.linear_algebra"].state == "provisionally_satisfied"
    assert by_id["major.algorithms"].pending_grade_risk is False


def test_min_grade_policy_assume_not_met_reopens_it(audit: ExtractedAudit) -> None:
    state = derive_state(audit, Assumptions(min_grade_pending_policy="assume_not_met"))
    assert states(state)["major.linear_algebra"] == "open"


def test_what_if_i_fail_cs_3240(audit: ExtractedAudit) -> None:
    baseline = derive_state(audit)
    failed = derive_state(
        audit, Assumptions(in_progress_policy="per_course", failed_courses=["CS 3240"])
    )
    s = states(failed)
    assert s["major.algorithms"] == "open"
    assert s["major.total"] == "open"  # loses the in-progress credits it counted on
    assert s["major.linear_algebra"] == "provisionally_satisfied"  # MATH 2522 still assumed passed
    assert "CS 3240" not in failed.counted_courses  # prerequisite no longer met
    assert "CS 3240" not in failed.unplannable_courses  # can be retaken
    assert failed.credits.earned_plus_in_progress == baseline.credits.earned_plus_in_progress - 3
    assert failed.credits.earned == baseline.credits.earned


def test_assume_fail_drops_every_in_progress_course(audit: ExtractedAudit) -> None:
    state = derive_state(audit, Assumptions(in_progress_policy="assume_fail"))
    assert not {"CS 3240", "MATH 2522"} & state.counted_courses
    assert states(state)["major.algorithms"] == "open"
    assert state.credits.earned_plus_in_progress == state.credits.earned


def test_only_the_track_being_followed_stays_open(audit: ExtractedAudit) -> None:
    state = derive_state(audit)
    s = states(state)
    assert s["chinese.tracks.track_2.chin_4200"] == "open"
    assert s["chinese.tracks.track_1"] == "not_applicable"
    assert s["chinese.tracks.track_1.chin_1100"] == "not_applicable"
    assert "chinese.tracks.track_1.chin_1100" not in state.open_requirement_ids
    assert state.warnings == ()


def test_no_track_started_keeps_all_open_and_warns(audit: ExtractedAudit) -> None:
    audit.requirements = [
        r for r in audit.requirements if r.req_id != "chinese.tracks.track_2.chin_2100"
    ]
    state = derive_state(audit)
    assert states(state)["chinese.tracks.track_1.chin_1100"] == "open"
    assert any("chinese.tracks" in w for w in state.warnings)


def test_derive_state_is_pure(audit: ExtractedAudit) -> None:
    before = audit.model_dump()
    assert derive_state(audit) == derive_state(audit)
    assert audit.model_dump() == before
