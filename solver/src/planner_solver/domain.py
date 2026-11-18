"""Catalog, section and student-term data the solver reasons over (filled by M3 ingestion)."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Day = Literal["M", "T", "W", "R", "F", "S", "U"]  # R = Thursday, U = Sunday
DAYS: tuple[Day, ...] = ("M", "T", "W", "R", "F", "S", "U")
Modality = Literal["in_person", "online", "hybrid"]
Tri = Literal["yes", "no", "unknown"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Meeting(_Model):
    days: tuple[Day, ...]
    start: int  # minutes after midnight
    end: int


class Section(_Model):
    section_id: str  # unique within the term, e.g. "CS 2100 A"
    course: str
    component: str = "LEC"  # LEC / LAB / DIS ...: a course needs one section per component
    meetings: tuple[Meeting, ...] = ()
    instructors: tuple[str, ...] = ()
    seats_open: int | None = None
    capacity: int | None = None
    modality: Modality | None = None
    campus: str | None = None

    @property
    def is_lab(self) -> bool:
        return self.component == "LAB"


class CoursePrereq(_Model):
    kind: Literal["course"]
    code: str
    min_grade: str | None = None
    concurrent_ok: bool = False


class AllPrereq(_Model):
    kind: Literal["and"]
    items: list[Prereq]


class AnyPrereq(_Model):
    kind: Literal["or"]
    items: list[Prereq]


class StandingPrereq(_Model):
    kind: Literal["standing"]
    minimum: Literal["sophomore", "junior", "senior", "graduate"]


class PermissionPrereq(_Model):
    kind: Literal["permission"]
    text: str


class UnparsedPrereq(_Model):
    kind: Literal["unparsed"]
    text: str


Prereq = Annotated[
    CoursePrereq | AllPrereq | AnyPrereq | StandingPrereq | PermissionPrereq | UnparsedPrereq,
    Field(discriminator="kind"),
]
AllPrereq.model_rebuild()
AnyPrereq.model_rebuild()


class Course(_Model):
    code: str
    title: str
    credits: float
    attributes: frozenset[str] = frozenset()
    prereq: Prereq | None = None

    @property
    def subject(self) -> str:
        return self.code.split(" ")[0]

    @property
    def number(self) -> str:
        return self.code.split(" ")[1]

    @property
    def level(self) -> int:
        digits = re.match(r"\d", self.number)
        return int(digits.group(0)) * 1000 if digits else 0


class TermData(_Model):
    term: str  # e.g. "2027SP" or a source's own code ("202701")
    courses: dict[str, Course]
    sections: tuple[Section, ...]
    prereqs_loaded: bool = True  # False: course prerequisites are unknown, not absent


class RequirementTarget(_Model):
    title: str
    # rule codes/selectors: "CS 2100", "CS 3@", "@ @ with attribute = AH1"
    selectors: tuple[str, ...]
    excluded: tuple[str, ...] = ()  # courses that don't count ("Except ...")
    needed: float | None = None  # how much is still needed, in `unit` (None: not stated)
    unit: Literal["credits", "courses"] | None = None


class StudentTerm(_Model):
    """What the solver needs from derive_state for one term."""

    counted_courses: frozenset[str]  # satisfy prerequisites
    unplannable_courses: frozenset[str]  # never proposed
    open_requirements: dict[str, RequirementTarget]
    standing: Literal["freshman", "sophomore", "junior", "senior", "graduate"] | None = None


_ATTRIBUTE = re.compile(r"^@ @ with attribute = ([A-Z0-9]+)$")
_RANGE = re.compile(r"^([A-Z]{2,5}) (\d{4}):(\d{4})$")
_WILD = re.compile(r"^(@|[A-Z]{2,5}) (@|\d{1,3}@)$")


def resolve_selector(selector: str, courses: dict[str, Course]) -> set[str] | None:
    """Course codes a rule selector stands for; None if the selector isn't understood."""
    if selector in courses:
        return {selector}
    if m := _ATTRIBUTE.match(selector):
        return {c.code for c in courses.values() if m.group(1) in c.attributes}
    if m := _RANGE.match(selector):
        subject, low, high = m.group(1), int(m.group(2)), int(m.group(3))
        return {
            c.code
            for c in courses.values()
            if c.subject == subject and c.number[:4].isdigit() and low <= int(c.number[:4]) <= high
        }
    if m := _WILD.match(selector):
        subject, number = m.groups()
        prefix = number.rstrip("@")
        return {
            c.code
            for c in courses.values()
            if (subject == "@" or c.subject == subject) and c.number.startswith(prefix)
        }
    if re.fullmatch(r"[A-Z]{2,5} [0-9X]{4}[A-Z]?", selector):
        return set()  # a well-formed code that simply isn't offered/known
    return None


_STANDING_ORDER = {"freshman": 0, "sophomore": 1, "junior": 2, "senior": 3, "graduate": 4}


def prereq_met(prereq: Prereq | None, student: StudentTerm) -> Tri:
    """Three-valued: permission and unparsed nodes are 'unknown', never silently 'yes'."""
    if prereq is None:
        return "yes"
    if isinstance(prereq, CoursePrereq):
        return "yes" if prereq.code in student.counted_courses else "no"
    if isinstance(prereq, StandingPrereq):
        if student.standing is None:
            return "unknown"
        # strict (owner decision): below the required standing blocks the course
        ok = _STANDING_ORDER[student.standing] >= _STANDING_ORDER[prereq.minimum]
        return "yes" if ok else "no"
    if isinstance(prereq, PermissionPrereq | UnparsedPrereq):
        return "unknown"
    results = [prereq_met(item, student) for item in prereq.items]
    if isinstance(prereq, AllPrereq):
        if "no" in results:
            return "no"
        return "unknown" if "unknown" in results else "yes"
    if "yes" in results:
        return "yes"
    return "unknown" if "unknown" in results else "no"


def unknown_reasons(prereq: Prereq | None, student: StudentTerm) -> list[str]:
    """Why prereq_met is 'unknown': the specific parts that couldn't be verified."""
    if prereq is None or prereq_met(prereq, student) != "unknown":
        return []
    if isinstance(prereq, StandingPrereq):
        return [f"requires {prereq.minimum} standing (your standing isn't on the audit)"]
    if isinstance(prereq, PermissionPrereq):
        return [f"needs permission: {prereq.text}"]
    if isinstance(prereq, UnparsedPrereq):
        return [f"check: {prereq.text}"]
    if isinstance(prereq, AllPrereq | AnyPrereq):
        return [r for item in prereq.items for r in unknown_reasons(item, student)]
    return []


def blocking_reasons(prereq: Prereq | None, student: StudentTerm) -> list[str]:
    """Why prereq_met is 'no', in the student's terms."""
    if prereq is None or prereq_met(prereq, student) != "no":
        return []
    if isinstance(prereq, CoursePrereq):
        return [f"requires {prereq.code}"]
    if isinstance(prereq, StandingPrereq):
        return [f"requires {prereq.minimum} standing (your audit says {student.standing})"]
    if isinstance(prereq, AllPrereq):
        return [r for item in prereq.items for r in blocking_reasons(item, student)]
    if isinstance(prereq, AnyPrereq):
        options = " or ".join(r for item in prereq.items for r in blocking_reasons(item, student))
        return [f"needs one of: {options}"] if options else []
    return []
