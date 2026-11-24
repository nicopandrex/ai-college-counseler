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
    assert "ECON 2020 B  Macroeconomics (3 cr)  TR 11:30am–12:45pm  · Ana Diaz" in text
    assert "Schedule 1 · 3 credits" in text
    assert "→ Macroeconomics" in text


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
    assert "• not with Ana Diaz for ECON 2020" in text and "• only sections with open seats" in text
    first_fix = text.index("1. Drop “only sections with open seats”")
    assert first_fix < text.index("2. Drop “not with Ana Diaz for ECON 2020”")


def test_unverified_prerequisite_is_flagged_on_the_course_line() -> None:
    from planner_solver.domain import PermissionPrereq

    courses = dict(TERM.courses)
    courses["ECON 2020"] = courses["ECON 2020"].model_copy(
        update={"prereq": PermissionPrereq(kind="permission", text="instructor permission")}
    )
    term = TERM.model_copy(update={"courses": courses})
    s = spec(c("c1", "include_course", course="ECON 2020"), c("c2", "credit_range", min=3, max=3))
    text = render_result(solve_term(s, term, STUDENT), s, term, STUDENT)
    assert "Macroeconomics (3 cr)" in text and "⚠ needs permission: instructor permission" in text
    assert "note:" not in text  # no list of unrelated courses


def test_each_course_says_what_it_counts_toward_with_progress() -> None:
    from planner_solver.domain import RequirementTarget

    student = STUDENT.model_copy(
        update={
            "open_requirements": {
                "SEM": RequirementTarget(
                    title="Senior Seminar", selectors=("CS 3200",), needed=1, unit="courses"
                ),
                "ELEC": RequirementTarget(
                    title="CS electives", selectors=("CS 3@",), needed=6, unit="credits"
                ),
            }
        }
    )
    s = spec(c("c1", "include_course", course="CS 3200"), c("c2", "credit_range", min=6, max=6))
    result = solve_term(s, TERM, student)
    text = render_result(result, s, TERM, student)
    assert "→ Senior Seminar (1 of 1 class); CS electives (6 of 6 credits)" in text


def test_requested_course_outside_open_requirements_is_labelled() -> None:
    from planner_solver.domain import RequirementTarget

    student = STUDENT.model_copy(
        update={
            "open_requirements": {
                "HUM": RequirementTarget(
                    title="Humanities", selectors=("HIST 1010",), needed=1, unit="courses"
                )
            }
        }
    )
    s = spec(c("c1", "include_course", course="ECON 2020"), c("c2", "credit_range", min=6, max=6))
    text = render_result(solve_term(s, TERM, student), s, TERM, student)
    assert "→ you asked for this; it doesn't count toward an open requirement" in text


def test_three_schedules_shown_and_alternatives_read_as_swaps() -> None:
    s = spec(c("c1", "credit_range", min=9, max=9))
    result = solve_term(s, TERM, STUDENT)
    text = render_result(result, s, TERM, STUDENT)
    assert len(result.schedules) == 5 and "Schedule 3" in text and "Schedule 4" not in text
    assert "Schedule 2 · 9 credits: like schedule 1, but" in text
    assert "\n  − " in text and "\n  + " in text


def test_a_single_impossible_request_says_why_in_catalog_facts() -> None:
    from planner_solver.domain import RequirementTarget

    student = STUDENT.model_copy(
        update={
            "open_requirements": {
                **STUDENT.open_requirements,
                "CAPSTONE": RequirementTarget(title="Capstone", selectors=("CS 4999",)),
            }
        }
    )
    s = spec({**c("c1", "satisfy_requirement", req_ids=["CAPSTONE"]), "source_text": "capstone"})
    text = render_result(solve_term(s, TERM, student), s, TERM, student)
    assert text.startswith("I can't make this work this term: something for Capstone.")
    assert "Why: Capstone: CS 4999 requires CS 3999." in text
    assert "can't all hold" not in text


def test_a_lost_bottleneck_gets_a_heads_up_naming_the_rule() -> None:
    s = spec({**c("c1", "no_later_than", time="10:00"), "source_text": "done by 10"})
    text = render_result(solve_term(s, TERM, STUDENT), s, TERM, STUDENT)
    assert text.splitlines()[-1].startswith("Heads up: done by 10:00am rules out ")
    assert "ECON 2020 (the only option for Macroeconomics)" in text
