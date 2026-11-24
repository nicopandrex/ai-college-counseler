from term_fixtures import STUDENT, TERM, c, spec

from planner_solver.present import render_result
from planner_solver.term import solve_term


def test_schedule_text_is_built_only_from_solver_and_catalog_data() -> None:
    s = spec(
        c("c1", "include_course", course="ECON 2020"),
        c("c2", "credit_range", min=3, max=3),
        c("c3", "open_seats_only", value=True),
    )
    text = render_result(solve_term(s, TERM, STUDENT), s, TERM, STUDENT)
    assert "ECON 2020 B  Macroeconomics (3 cr)  TR 11:30–12:45  · Ana Diaz" in text
    assert "Schedule 1 · 3 credits" in text
    assert "counts toward: Macroeconomics" in text


def test_conflicts_are_named_by_the_users_words_with_ranked_fixes() -> None:
    s = spec(
        {**c("c1", "include_course", course="ECON 2020"), "source_text": "macro"},
        {
            **c(
                "c2",
                "instructor_preference",
                weight=4,
                name="Ana Diaz",
                polarity="exclude",
                course="ECON 2020",
            ),
            "source_text": "not with Diaz",
        },
        {**c("c3", "open_seats_only", weight=2, value=True), "source_text": "only open seats"},
    )
    text = render_result(solve_term(s, TERM, STUDENT), s, TERM, STUDENT)
    assert "can't all hold at once" in text
    assert "“not with Diaz”" in text and "“only open seats”" in text
    first_fix = text.index("1. Drop “only open seats”")
    assert first_fix < text.index("2. Drop “not with Diaz”")


def test_unverified_prerequisite_is_flagged_on_the_course_line() -> None:
    from planner_solver.domain import PermissionPrereq

    courses = dict(TERM.courses)
    courses["ECON 2020"] = courses["ECON 2020"].model_copy(
        update={"prereq": PermissionPrereq(kind="permission", text="instructor permission")}
    )
    term = TERM.model_copy(update={"courses": courses})
    s = spec(c("c1", "include_course", course="ECON 2020"), c("c2", "credit_range", min=3, max=3))
    text = render_result(solve_term(s, term, STUDENT), s, term, STUDENT)
    assert "Macroeconomics (3 cr)" in text and "⚠ check prerequisite" in text
    assert "note:" not in text  # no list of unrelated courses
