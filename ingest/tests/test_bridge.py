import json
from pathlib import Path

from synth_degreeworks import sample_audit

from planner_ingest.bridge import parse_still_needed, student_term
from planner_ingest.config import load_school_config
from planner_ingest.extraction import ExtractedAudit
from planner_ingest.layout import parse_layout
from planner_ingest.state import derive_state
from planner_ingest.validate import finalize

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_extraction.json"


def test_still_needed_course_lists_carry_the_subject_forward() -> None:
    selectors, excluded = parse_still_needed(
        "Still needed: 3 Credits in CHIN 1070 or 1012 or HST 1440 or PHIL 1750"
    )
    assert selectors == ["CHIN 1070", "CHIN 1012", "HST 1440", "PHIL 1750"]
    assert excluded == []


def test_still_needed_ranges_and_wildcards() -> None:
    selectors, _ = parse_still_needed("Still needed: 6 Credits in CS 3000:3990 or 3993 or 5@ or 6@")
    assert selectors == ["CS 3000:3990", "CS 3993", "CS 5@", "CS 6@"]


def test_still_needed_attribute_with_exception() -> None:
    text = (
        "Still needed: 2 Classes in @ @ with attribute = AH3 Except @ @ with discipline = CAS "
        "and course number = 1720"
    )
    selectors, excluded = parse_still_needed(text)
    assert selectors == ["@ @ with attribute = AH3"]
    assert excluded == ["CAS 1720"]


def test_still_needed_without_a_course_list() -> None:
    assert parse_still_needed("Still needed: See Catamount Core section") == ([], [])
    assert parse_still_needed(None) == ([], [])


def test_student_term_targets_only_open_plannable_requirements(tmp_path: Path) -> None:
    layout = parse_layout(sample_audit(tmp_path / "a.pdf"), load_school_config("uvm"))
    raw = ExtractedAudit.model_validate(json.loads(FIXTURE.read_text()))
    audit, _ = finalize(raw, layout, load_school_config("uvm"))  # dotted, structure-derived ids
    term = student_term(audit, derive_state(audit))
    assert set(term.open_requirements) == {
        "bachelor_science_test.senior_seminar",  # still needed: 1 Class in CS 3920
        "bachelor_science_test.choose_one_track.track_1.calculus_ii",  # rule: MATH 1248
    }  # groups (CHOOSE ONE TRACK, TRACK 1) are covered through their children
    assert term.open_requirements["bachelor_science_test.senior_seminar"].selectors == ("CS 3920",)
    assert "CS 2500" in term.unplannable_courses  # in progress
    assert "CS 2500" in term.counted_courses


def test_still_needed_prefix_is_optional() -> None:
    text = (
        "2 Classes in @ @ with attribute = AH3 "
        "Except @ @ with discipline = CAS and course number = 1720"
    )
    assert parse_still_needed(text) == (["@ @ with attribute = AH3"], ["CAS 1720"])
    assert parse_still_needed("You must complete 2 courses in the major") == ([], [])


def test_standing_comes_from_the_audits_own_words() -> None:
    from planner_ingest.bridge import standing_from

    assert standing_from("03 - Junior") == "junior"
    assert standing_from("Senior") == "senior"
    assert standing_from("Graduate") == "graduate"
    assert standing_from(None) is None
    assert standing_from("Level 3") is None  # unknown wording: not guessed


def test_needed_amount_and_unit_come_from_the_still_needed_line() -> None:
    from planner_ingest.bridge import needed_amount

    assert needed_amount("Still needed: 6 Credits in CS 3000:3990 or 3993") == (6.0, "credits")
    assert needed_amount("2 Classes in @ @ with attribute = AH3") == (2.0, "courses")
    assert needed_amount("Still needed: 1 Class in CS 3920") == (1.0, "courses")
    assert needed_amount("Still needed: See Catamount Core section") == (None, None)


def test_targets_carry_readable_titles_and_amounts(tmp_path: Path) -> None:
    layout = parse_layout(sample_audit(tmp_path / "a.pdf"), load_school_config("uvm"))
    raw = ExtractedAudit.model_validate(json.loads(FIXTURE.read_text()))
    audit, _ = finalize(raw, layout, load_school_config("uvm"))
    target = student_term(audit, derive_state(audit)).open_requirements[
        "bachelor_science_test.choose_one_track.track_1.calculus_ii"
    ]
    assert target.title == "CHOOSE ONE TRACK › TRACK 1 › Calculus II"
    assert (target.needed, target.unit) == (4.0, "credits")  # from the rule: 4 credits of MATH 1248
