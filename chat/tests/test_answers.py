"""Degree questions answered from the audit and the catalog (synthetic ECON-style data)."""

from planner_chat.answers import Advisor, requirement_hint, term_name
from planner_solver.domain import (
    AllPrereq,
    Course,
    CoursePrereq,
    Meeting,
    RequirementTarget,
    Section,
    StudentTerm,
    TermData,
)


def course(code: str, credits: float = 3, prereq=None, attrs: tuple[str, ...] = ()) -> Course:
    return Course(
        code=code,
        title=f"Title {code}",
        credits=credits,
        prereq=prereq,
        attributes=frozenset(attrs),
    )


def need(code: str, concurrent: bool = False) -> CoursePrereq:
    return CoursePrereq(kind="course", code=code, concurrent_ok=concurrent)


COURSES = {
    "ECON 1400": course("ECON 1400"),
    "ECON 1450": course("ECON 1450"),
    "ECON 1990": course("ECON 1990", credits=1),
    "ECON 2400": course("ECON 2400"),  # not offered this term
    "ECON 2450": course(
        "ECON 2450", prereq=AllPrereq(kind="and", items=[need("ECON 1400"), need("ECON 1450")])
    ),
    "ECON 2460": course("ECON 2460", prereq=need("ECON 1450", concurrent=True)),
    "ECON 3500": course("ECON 3500", prereq=need("ECON 2450")),
    "SOC 1100": course("SOC 1100", attrs=("S1",)),
}
SECTIONS = tuple(
    Section(
        section_id=f"{code} A",
        course=code,
        meetings=(Meeting(days=("M", "W"), start=13 * 60 + 10, end=14 * 60),),
        instructors=("S. Smith",),
    )
    for code in COURSES
    if code != "ECON 2400"
)
TERM = TermData(term="2027SP", courses=COURSES, sections=SECTIONS)
STUDENT = StudentTerm(
    counted_courses=frozenset(),
    unplannable_courses=frozenset({"ECON 1990"}),
    open_requirements={
        "major.macro": RequirementTarget(
            title="FOUNDATIONS › Principles of Macroeconomics",
            selectors=("ECON 1400",),
            needed=1,
            unit="courses",
        ),
        "major.theory": RequirementTarget(
            title="FOUNDATIONS › Macroeconomic Theory",
            selectors=("ECON 2400 with resident= Y",),
            needed=1,
            unit="courses",
        ),
        "core.s1": RequirementTarget(
            title="Liberal Arts › Social Sciences (S1)",
            selectors=("@ @ with attribute = S1",),
            needed=6,
            unit="credits",
        ),
        "major.open": RequirementTarget(
            title="ELECTIVES › OPEN LEVEL",
            selectors=("ECON 1010:1990", "ECON 2100:2990"),
            needed=1,
            unit="courses",
        ),
    },
)


def advisor() -> Advisor:
    return Advisor(TERM, STUDENT, in_progress=("CS 3050",))


def test_term_codes_read_as_seasons() -> None:
    assert term_name("2027SP") == "Spring 2027" and term_name("202701") == "202701"


def test_what_is_left_is_grouped_and_one_course_rules_say_their_credits() -> None:
    answer = advisor().remaining()
    assert answer.text.startswith("You have 4 requirements left:")
    assert "FOUNDATIONS\n  • Principles of Macroeconomics: ECON 1400 (3 credits)" in answer.text
    assert "Social Sciences (S1): 6 credits (about 2 courses)" in answer.text
    assert "OPEN LEVEL: 1 course (1–3 credits each)" in answer.text
    assert "counting your 1 in-progress course as passed" in answer.text
    assert answer.suggestions[-1].message == "Plan my next semester"


def test_requirement_details_add_up_credits_and_say_what_is_offered() -> None:
    answer = advisor().requirement_details(["major.macro", "major.theory"])
    assert answer.text.startswith("Together those come to 6 credits:")
    assert (
        "Principles of Macroeconomics: ECON 1400 (3 credits).\n"
        "  It's offered in Spring 2027, and you can take it." in answer.text
    )
    assert "ECON 2400 Title ECON 2400 isn't offered in Spring 2027." in answer.text
    assert answer.suggestions[0].message == "Add ECON 1400 to my schedule"
    assert advisor().requirement_details([]).text == "Which requirement do you mean?"


def test_what_else_can_i_take_alongside_a_course_separates_now_same_term_and_later() -> None:
    text = advisor().course_options(["ECON"], ["ECON 1450"], []).text
    assert text.startswith("4 ECON courses you haven't taken are offered in Spring 2027.")
    assert "So ECON 1450 isn't a prerequisite for everything: 3 of the 4 need it" in text
    assert "Alongside ECON 1450, you can take 1: ECON 1400 Title ECON 1400." in text
    assert "1 can be taken in the same term as ECON 1450: ECON 2460." in text
    assert "1 need ECON 1450 finished first, so not this term: ECON 2450." in text
    assert "1 need other courses first (e.g. ECON 3500: requires ECON 2450)." in text


def test_subject_comes_from_the_course_when_none_is_named() -> None:
    assert advisor().course_options([], ["ECON 1450"], []).text.startswith("4 ECON courses")
    assert advisor().course_options([], [], []).text.startswith("Which subject or requirement")


def test_course_info_is_a_short_paragraph_with_prerequisites_and_what_it_unlocks() -> None:
    answer = advisor().course_info(["econ 1450"])
    assert answer.text == (
        "ECON 1450 Title ECON 1450 is 3 credits. Spring 2027 has 1 section: "
        "A MW 1:10–2:00pm (S. Smith). It has no prerequisites. It's a prerequisite for 2 "
        "courses this term: ECON 2450 and ECON 2460. It counts toward OPEN LEVEL."
    )
    assert [s.message for s in answer.suggestions] == [
        "Add ECON 1450 to my schedule",
        "What other ECON classes can I take alongside ECON 1450?",
    ]
    blocked = advisor().course_info(["ECON 3500"]).text
    assert "You can't take it yet: requires ECON 2450." in blocked


def test_requirement_hints_name_the_one_course_or_its_credits() -> None:
    a = advisor()
    assert requirement_hint(a, "major.macro", STUDENT.open_requirements["major.macro"]) == (
        "ECON 1400 · 3 cr"
    )
    assert requirement_hint(a, "major.open", STUDENT.open_requirements["major.open"]) == (
        "1–3 cr each"
    )


def test_missing_prerequisites_read_as_one_phrase() -> None:
    text = advisor().course_info(["ECON 2450"]).text
    assert "You can't take it yet: requires ECON 1400 and ECON 1450." in text


def test_a_hint_names_a_course_only_when_that_one_course_is_needed() -> None:
    two = RequirementTarget(title="Two from", selectors=("ECON 1400",), needed=2, unit="courses")
    assert requirement_hint(advisor(), "major.macro", two) == "3 cr each"


def test_requirement_names_drop_the_audits_counting_text() -> None:
    from planner_chat.answers import short

    assert short("ELECTIVES › OPEN LEVEL. 1 additional course/3 credits from the following") == (
        "Open Level"
    )
    assert short("HUMANITIES. 2 courses with an AH3 designation") == "Humanities"
    assert short("Liberal Arts Categories › Social Sciences (S1)") == "Social Sciences (S1)"


def test_a_plan_says_what_it_finishes_what_it_helps_and_what_stays_open() -> None:
    from planner_chat.answers import Plan

    plan = Plan(
        "Plan A",
        9,
        ["ECON 1400", "ECON 1450", "SOC 1100"],
        {"major.macro": ["ECON 1400"], "major.open": ["ECON 1450"], "core.s1": ["SOC 1100"]},
    )
    answer = advisor().plan_progress([plan], earned=80, in_progress=15)
    assert answer.text.splitlines() == [
        "With Plan A (9 credits), you'd finish 2 of your 4 open requirements and make "
        "progress on 1 more, so 2 would still be open.",
        "Finished: Principles of Macroeconomics and OPEN LEVEL.",
        "Partly done: Social Sciences (S1) (3 of 6 credits).",
        "Not touched by Plan A: Macroeconomic Theory.",
        "You'd be at 104 credits (80 earned, 15 in progress and 9 from Plan A).",
    ]
    assert [s.message for s in answer.suggestions] == [
        "Compare my plans",
        "What courses count for Macroeconomic Theory?",
    ]


def test_plans_are_compared_by_what_they_finish() -> None:
    from planner_chat.answers import Plan

    a = Plan(
        "Plan A",
        9,
        ["ECON 1400", "SOC 1100"],
        {"major.macro": ["ECON 1400"], "core.s1": ["SOC 1100"]},
    )
    b = Plan("Plan B", 3, ["SOC 1100"], {"core.s1": ["SOC 1100"]})
    text = advisor().plan_progress([a, b]).text
    assert text.splitlines() == [
        "Plan A (9 credits) finishes 1 of your 4 open requirements, helps with 1 more and "
        "leaves 3 open.",
        "Plan B (3 credits) finishes 0 of your 4 open requirements, helps with 1 more and "
        "leaves 4 open.",
        "Plan A finishes the most.",
    ]
    assert advisor().plan_progress([]).text.startswith("There's no plan yet.")


def test_tied_plans_say_they_tie() -> None:
    from planner_chat.answers import Plan

    a = Plan("Plan A", 3, ["ECON 1400"], {"major.macro": ["ECON 1400"]})
    b = Plan("Plan B", 3, ["ECON 1400"], {"major.macro": ["ECON 1400"]})
    c = Plan("Plan C", 3, ["SOC 1100"], {"core.s1": ["SOC 1100"]})
    assert (
        advisor()
        .plan_progress([a, b])
        .text.endswith("They all finish 1, so pick by the times that suit you.")
    )
    assert (
        advisor().plan_progress([a, b, c]).text.endswith("Plan A and Plan B tie for the most (1).")
    )
