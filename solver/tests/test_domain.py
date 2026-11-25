"""Requirement selectors from DegreeWorks text -> course codes."""

from term_fixtures import COURSES, STUDENT, TERM, spec

from planner_solver.domain import RequirementTarget, resolve_selector
from planner_solver.term import solve_term


def test_a_residency_qualifier_means_taken_here_which_every_planned_course_is() -> None:
    assert resolve_selector("ECON 2020 with resident= Y", COURSES) == {"ECON 2020"}
    assert resolve_selector("ECON 2020 with resident = Y", COURSES) == {"ECON 2020"}


def test_an_unreadable_rule_is_named_in_the_students_terms() -> None:
    odd = RequirementTarget(title="Macroeconomic Theory", selectors=("ECON 2020 with grade = B",))
    student = STUDENT.model_copy(
        update={"open_requirements": {**STUDENT.open_requirements, "major.macro_theory": odd}}
    )
    result = solve_term(spec(), TERM, student)
    assert any("Macroeconomic Theory" in w for w in result.warnings)
    assert not any("major.macro_theory" in w or "cannot interpret" in w for w in result.warnings)
