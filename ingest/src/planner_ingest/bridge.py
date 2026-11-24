"""Student state (derive_state) -> what the term solver needs (StudentTerm).

For an open requirement the courses that can satisfy it come from DegreeWorks' own
machine-generated "Still needed: N Classes/Credits in ..." line when present (deterministic),
otherwise from the extracted rule's course lists.
"""

from __future__ import annotations

import re

from planner_ingest.extraction import (
    AllOfRule,
    AnyOfRule,
    CourseListRule,
    ExtractedAudit,
    Rule,
    UnparsedRule,
)
from planner_ingest.state import StudentState
from planner_solver.domain import RequirementTarget, StudentTerm

_LIST = re.compile(
    r"^(?:Still needed:\s*)?\d+(?:\.\d+)?\s+(?:Classes|Class|Credits|Credit)\s+in\s+(.+)$", re.I
)
_EXCEPT_COURSE = re.compile(r"@ @ with discipline = ([A-Z]{2,5}) and course number = (\d{4}[A-Z]?)")
_SUBJECT = re.compile(r"^([A-Z]{2,5}) (.+)$")


def parse_still_needed(text: str | None) -> tuple[list[str], list[str]]:
    """(selectors, excluded course codes) from a 'Still needed: N ... in X or Y' line."""
    match = _LIST.search(" ".join((text or "").split()))
    if not match:
        return [], []
    body, _, exception = match.group(1).partition(" Except ")
    excluded = [f"{s} {n}" for s, n in _EXCEPT_COURSE.findall(exception)]
    if body.startswith("@ @ with attribute"):
        return [body.strip()], excluded
    selectors, subject = [], None
    for part in (p.strip() for p in body.split(" or ")):
        if m := _SUBJECT.match(part):
            subject = m.group(1)
            selectors.append(part)
        elif subject:
            selectors.append(f"{subject} {part}")
    return selectors, excluded


def _rule_selectors(rule: Rule) -> list[str]:
    if isinstance(rule, CourseListRule):
        return list(rule.from_)
    if isinstance(rule, AllOfRule | AnyOfRule):
        return [s for item in rule.items for s in _rule_selectors(item)]
    return []


def student_term(audit: ExtractedAudit, state: StudentState) -> StudentTerm:
    by_id = {r.req_id: r for r in audit.requirements}
    groups = {s.parent_id for s in state.requirements if s.parent_id}
    targets: dict[str, RequirementTarget] = {}
    for status in state.requirements:
        if status.state != "open" or status.req_id in groups:
            continue  # a group is satisfied through its child requirements
        req = by_id[status.req_id]
        selectors, excluded = parse_still_needed(req.still_needed_text)
        if not selectors and isinstance(req.rule, UnparsedRule):
            selectors, excluded = parse_still_needed(req.rule.text)
        if not selectors:
            selectors = _rule_selectors(req.rule)
        if selectors:
            targets[req.req_id] = RequirementTarget(
                title=req.title, selectors=tuple(selectors), excluded=tuple(excluded)
            )
    return StudentTerm(
        counted_courses=state.counted_courses,
        unplannable_courses=state.unplannable_courses,
        open_requirements=targets,
    )
