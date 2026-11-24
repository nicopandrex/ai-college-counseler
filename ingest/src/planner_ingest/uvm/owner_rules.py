"""Prerequisite facts stated by the owner that the SOC comments don't carry.

- 2026-11-18: any course titled "Senior Seminar" requires senior standing to enroll (blocking).
"""

from __future__ import annotations

import re

from planner_solver.domain import AllPrereq, Course, Prereq, StandingPrereq

SENIOR_SEMINAR = re.compile(r"\bsenior seminar\b", re.I)
SENIOR = StandingPrereq(kind="standing", minimum="senior")


def apply_owner_rules(courses: dict[str, Course]) -> dict[str, Course]:
    out = {}
    for code, course in courses.items():
        if SENIOR_SEMINAR.search(course.title) and not _requires_senior(course.prereq):
            prereq: Prereq = (
                SENIOR
                if course.prereq is None
                else AllPrereq(kind="and", items=[course.prereq, SENIOR])
            )
            course = course.model_copy(update={"prereq": prereq})
        out[code] = course
    return out


def _requires_senior(prereq: Prereq | None) -> bool:
    if prereq == SENIOR:
        return True
    return isinstance(prereq, AllPrereq) and any(_requires_senior(p) for p in prereq.items)
