from pathlib import Path

from synth_degreeworks import sample_audit

from planner_ingest.config import load_school_config
from planner_ingest.ids import requirement_ids, slug
from planner_ingest.layout import parse_layout

UVM = load_school_config("uvm")


def test_slug_is_short_and_stable() -> None:
    assert slug("Arts & Humanities (AH1, AH2, AH3)") == "arts_humanities_ah1_ah2_ah3"
    assert (
        slug("LANGUAGE: 2 courses/at least 6 credits in the same")
        == "language_2_courses_at_least_6"
    )
    assert slug("") == "untitled"
    assert slug("Option A (recommended)") == "option_a_recommended"
    assert (
        slug("COMMON GROUND VALUES:1 course with a D1 designation")
        == "common_ground_values_1_course_d1"
    )


def test_ids_follow_document_structure_and_are_reproducible(tmp_path: Path) -> None:
    pdf = sample_audit(tmp_path / "a.pdf")
    first = requirement_ids(parse_layout(pdf, UVM))
    second = requirement_ids(parse_layout(pdf, UVM))
    assert first == second
    values = list(first.values())
    assert len(values) == len(set(values))
    assert "bachelor_science_test" in values
    assert "bachelor_science_test.choose_one_track.track_1.calculus_i" in values
    assert "electives.courses" in values
