"""A tiny hand-built term (synthetic) with known-correct answers."""

from __future__ import annotations

from typing import Any

from planner_solver.domain import (
    Course,
    CoursePrereq,
    Meeting,
    RequirementTarget,
    Section,
    StudentTerm,
    TermData,
)
from planner_solver.spec import ConstraintSpec


def hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def sec(
    sid: str,
    course: str,
    days: str,
    start: str,
    end: str,
    instructor: str = "Staff",
    component: str = "LEC",
    **extra: Any,
) -> Section:
    meeting = Meeting(days=tuple(days), start=hm(start), end=hm(end))  # type: ignore[arg-type]
    return Section(
        section_id=sid,
        course=course,
        component=component,
        meetings=(meeting,),
        instructors=(instructor,),
        **extra,
    )


COURSES = {
    "CS 3200": Course(code="CS 3200", title="Software Engineering", credits=3),
    "CS 3410": Course(code="CS 3410", title="Networks", credits=3),
    "ECON 2020": Course(code="ECON 2020", title="Macroeconomics", credits=3),
    "ENGL 2010": Course(code="ENGL 2010", title="Writing", credits=3, attributes=frozenset({"A2"})),
    "HIST 1010": Course(
        code="HIST 1010", title="World History", credits=3, attributes=frozenset({"HUM"})
    ),
    "SOC 1000": Course(
        code="SOC 1000", title="Sociology", credits=3, attributes=frozenset({"SOC"})
    ),
    "BIOL 1400": Course(code="BIOL 1400", title="Biology", credits=4),
    "CHEM 1400": Course(code="CHEM 1400", title="Chemistry", credits=4),
    "CS 1210": Course(code="CS 1210", title="Programming I", credits=3),
    "ART 1100": Course(code="ART 1100", title="Drawing", credits=3),
    "CS 4999": Course(
        code="CS 4999",
        title="Capstone",
        credits=3,
        prereq=CoursePrereq(kind="course", code="CS 3999"),
    ),
}

SECTIONS = (
    sec("CS 3200 A", "CS 3200", "MWF", "09:00", "09:50", "Pat Jones"),
    sec("CS 3200 B", "CS 3200", "TR", "13:15", "14:30", "Kim Lee"),
    sec("CS 3410 A", "CS 3410", "TR", "08:30", "09:45", "Kim Lee"),
    sec("ECON 2020 A", "ECON 2020", "MWF", "10:50", "11:40", "Smith, John A", seats_open=0),
    sec("ECON 2020 B", "ECON 2020", "TR", "11:30", "12:45", "Ana Diaz", seats_open=4),
    sec("ENGL 2010 A", "ENGL 2010", "MWF", "11:50", "12:40", "Sam Roe"),
    sec("HIST 1010 A", "HIST 1010", "TR", "14:50", "16:05", "Lou Park"),
    sec("SOC 1000 A", "SOC 1000", "MW", "15:30", "16:45", "Max Fox", modality="hybrid"),
    sec("BIOL 1400 A", "BIOL 1400", "MWF", "08:30", "09:20", "Ada Cole"),
    sec("BIOL 1400 L1", "BIOL 1400", "R", "13:15", "16:15", "Ada Cole", component="LAB"),
    sec("CHEM 1400 A", "CHEM 1400", "MW", "13:10", "14:25", "Ike Bay"),
    sec("CHEM 1400 L1", "CHEM 1400", "R", "16:30", "19:30", "Ike Bay", component="LAB"),
    sec("CS 1210 A", "CS 1210", "MWF", "13:10", "14:00"),
    sec("CS 4999 A", "CS 4999", "MWF", "14:20", "15:10"),
    sec("ART 1100 A", "ART 1100", "TR", "10:00", "11:15", "Lee Dion"),  # counts for nothing
)

TERM = TermData(term="2027SP", courses=COURSES, sections=SECTIONS)

STUDENT = StudentTerm(
    counted_courses=frozenset({"CS 1210", "CS 2100"}),
    unplannable_courses=frozenset({"CS 1210"}),
    open_requirements={
        "ENGL_A2": RequirementTarget(title="English A2", selectors=("@ @ with attribute = A2",)),
        "GENED_HUM": RequirementTarget(title="Humanities", selectors=("@ @ with attribute = HUM",)),
        "GENED_SOC": RequirementTarget(
            title="Social Sciences", selectors=("@ @ with attribute = SOC",)
        ),
        "CS_ELECTIVE": RequirementTarget(title="CS elective", selectors=("CS 3@", "CS 4@")),
        "SCIENCE": RequirementTarget(title="Lab science", selectors=("BIOL 1400", "CHEM 1400")),
        "MACRO": RequirementTarget(title="Macroeconomics", selectors=("ECON 2020",)),
    },
)


def c(
    cid: str, ctype: str, enforcement: str = "hard", weight: int = 5, **params: Any
) -> dict[str, Any]:
    return {
        "id": cid,
        "type": ctype,
        "params": params,
        "enforcement": enforcement,
        "weight": weight,
    }


def spec(*constraints: dict[str, Any]) -> ConstraintSpec:
    return ConstraintSpec.model_validate(
        {
            "spec_version": "0.1",
            "mode": "term",
            "target_term": "2027SP",
            "restatement": "test",
            "constraints": list(constraints),
        }
    )
