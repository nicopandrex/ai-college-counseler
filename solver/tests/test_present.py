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
    assert "covers: Macroeconomics" in text


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
