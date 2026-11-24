from pathlib import Path

import pytest
from synth_degreeworks import (
    Cell,
    IconMark,
    Text,
    block_header,
    build_pdf,
    requirement,
    sample_audit,
)

from planner_ingest.config import load_school_config
from planner_ingest.layout import AuditLayout, parse_layout

UVM = load_school_config("uvm")


@pytest.fixture(scope="module")
def layout(tmp_path_factory: pytest.TempPathFactory) -> AuditLayout:
    pdf = sample_audit(tmp_path_factory.mktemp("synth") / "audit.pdf")
    return parse_layout(pdf, UVM)


def test_summary_keeps_only_allow_listed_fields(layout: AuditLayout) -> None:
    assert layout.summary == {
        "Program": "Bachelor of Science",
        "Level": "Undergraduate",
        "Majors": "Computer Science",
    }
    assert "Example" not in layout.full_text
    assert "aexampl" not in layout.full_text


def test_blocks_and_their_status_words(layout: AuditLayout) -> None:
    assert [(b.title, b.status_text) for b in layout.blocks] == [
        ("Bachelor of Science, TEST", "INCOMPLETE"),
        ("Electives", None),
        ("In-progress", None),
    ]
    assert layout.blocks[0].info == [
        "Credits required: 120 Credits applied: 10 Catalog year: 2024-2025"
    ]


def test_one_row_per_icon_with_status_and_label(layout: AuditLayout) -> None:
    rows = layout.blocks[0].rows
    assert [(r.label, r.icon_status, r.level) for r in rows] == [
        ("Total Credit Requirement", "incomplete", 0),
        ("You meet the minimum Overall GPA requirement.", "complete", 0),
        ("Computer Programming I", "complete", 0),
        ("INTERMEDIATE LEVEL. 3 additional credits:", "in_progress", 0),
        ("Senior Seminar", "incomplete", 0),
        ("CHOOSE ONE TRACK:", "incomplete", 0),
        ("TRACK 1", "incomplete", 1),
        ("Calculus I", "complete", 2),
        ("Calculus II", "incomplete", 2),
    ]


def test_multi_line_still_needed_stays_with_its_row(layout: AuditLayout) -> None:
    total, gpa = layout.blocks[0].rows[:2]
    assert total.still_needed == (
        "Still needed: 120 credits are required. You currently have 10 "
        "(including in-progress courses); you need 110 more credits."
    )
    assert gpa.content == []


def test_nesting_follows_icon_indent(layout: AuditLayout) -> None:
    rows = {r.label: r for r in layout.blocks[0].rows}
    assert rows["TRACK 1"].parent_id == rows["CHOOSE ONE TRACK:"].row_id
    assert rows["Calculus I"].parent_id == rows["TRACK 1"].row_id
    assert rows["Senior Seminar"].parent_id is None


def test_course_lines_parsed_by_block_columns(layout: AuditLayout) -> None:
    rows = {r.label: r for r in layout.blocks[0].rows}
    (course,) = rows["INTERMEDIATE LEVEL. 3 additional credits:"].courses
    assert (course.code, course.title, course.grade, course.credits, course.term) == (
        "CS 2500",
        "Intro to Databases",
        "IP",
        3.0,
        "Fall 2026",
    )
    assert course.in_progress_marker
    (calc,) = rows["Calculus I"].courses
    assert (calc.grade, calc.credits, calc.in_progress_marker) == ("B+", 4.0, False)


def test_wide_column_blocks_and_transfer_codes(layout: AuditLayout) -> None:
    electives, in_progress = layout.blocks[1], layout.blocks[2]
    (transfer,) = electives.rows[0].courses
    assert (transfer.code, transfer.grade, transfer.credits) == ("ARTS 1XXX", "TR", 1.0)
    assert [c.code for c in in_progress.rows[0].courses] == ["CS 2500"]


def test_parsing_stops_at_legend(layout: AuditLayout) -> None:
    assert "Legend" not in layout.full_text
    assert layout.warnings == []


def test_unknown_icon_color_is_flagged_not_guessed(tmp_path: Path) -> None:
    odd = requirement(0, "complete", "Odd Row")
    odd.icons = [IconMark("custom", 0, 10.5, rgb=(0.6, 0.1, 0.9))]
    legend = Cell(height=30.0, texts=[Text(28.3, 8, "Legend", "Helvetica-Bold", 10)])
    pdf = build_pdf(tmp_path / "odd.pdf", [[block_header("Block", "INCOMPLETE", "x"), odd, legend]])
    result = parse_layout(pdf, UVM)
    (row,) = result.rows
    assert row.icon_status == "unknown"
    assert any("unrecognised icon color" in w for w in result.warnings)


def test_page_without_text_is_reported(tmp_path: Path) -> None:
    pdf = build_pdf(tmp_path / "blank.pdf", [[Cell(height=40.0)]])
    result = parse_layout(pdf, UVM)
    assert any("no text layer" in w for w in result.warnings)
