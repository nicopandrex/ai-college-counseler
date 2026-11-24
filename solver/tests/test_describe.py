"""Plain-English constraint wording (what the student sees instead of the LLM restatement)."""

from term_fixtures import STUDENT, TERM, c, spec

from planner_solver.describe import describe, summary
from planner_solver.spec import Constraint


def said(ctype: str, enforcement: str = "hard", **params) -> str:
    return describe(
        Constraint.model_validate(c("c1", ctype, enforcement, **params)),
        TERM,
        STUDENT.open_requirements,
    )


def test_time_and_day_rules_read_naturally() -> None:
    assert said("no_earlier_than", time="10:30") == "nothing before 10:30am"
    assert said("no_later_than", time="15:00", days=["M", "W"]) == (
        "done by 3:00pm on Mondays, Wednesdays"
    )
    assert said("free_day", day="R") == "Thursdays free"
    assert said("free_block", day="T", start="09:00", end="13:00", label="work") == (
        "Tuesdays 9:00am–1:00pm free (work)"
    )


def test_course_and_load_rules_read_naturally() -> None:
    assert said("include_course", course="ECON 2020") == "take ECON 2020 (Macroeconomics)"
    assert said("credit_range", min=12, max=12) == "12 credits"
    assert said("course_count_range", min=1, max=3) == "at most 3 classes"
    assert said("instructor_preference", name="Smith", polarity="exclude", course="ECON 2020") == (
        "not with Smith for ECON 2020"
    )
    assert said("satisfy_requirement", req_ids=["MACRO"]) == "something for Macroeconomics"
    assert said("modality", format="online") == "only online classes"


def test_summary_lists_what_was_kept_and_marks_preferences() -> None:
    s = spec(
        c("c1", "no_earlier_than", "soft", 3, time="10:00"),
        c("c2", "free_day", day="F"),
        c("default_credits", "credit_range", min=12, max=19),
        c("default_load_preference", "credit_range", "soft", 3, min=12, max=16),
    )
    assert summary(s, TERM, STUDENT.open_requirements) == (
        "Working with: nothing before 10:00am (if possible); Fridays free; "
        "a full-time load (12–19 credits)"
    )
