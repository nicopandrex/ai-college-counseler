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
_AMOUNT = re.compile(
    r"^(?:Still needed:\s*)?(\d+(?:\.\d+)?)\s+(Classes|Class|Credits|Credit)\s+in\b", re.I
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


def needed_amount(text: str | None) -> tuple[float | None, str | None]:
    """(6.0, 'credits') from 'Still needed: 6 Credits in ...'; (None, None) if not stated."""
    match = _AMOUNT.match(" ".join((text or "").split()))
    if not match:
        return None, None
    return float(match.group(1)), "credits" if match.group(2).lower().startswith(
        "credit"
    ) else "courses"


def display_title(req_id: str, titles: dict[str, str]) -> str:
    """'Electives 15 credits › 6 additional credits from the following' (block omitted)."""
    parts = req_id.split(".")
    chain = [
        titles[".".join(parts[:i])]
        for i in range(2, len(parts) + 1)
        if ".".join(parts[:i]) in titles
    ]
    return " › ".join(t.strip().rstrip(":").strip() for t in chain) or titles.get(req_id, req_id)


STANDINGS = ("freshman", "sophomore", "junior", "senior", "graduate")


def standing_from(class_standing: str | None) -> str | None:
    """'03 - Junior' -> 'junior'. Only the audit's stated words; never inferred from credits."""
    words = (class_standing or "").casefold()
    found = [s for s in STANDINGS if s in words]
    return found[0] if len(found) == 1 else None


def _rule_selectors(rule: Rule) -> list[str]:
    if isinstance(rule, CourseListRule):
        return list(rule.from_)
    if isinstance(rule, AllOfRule | AnyOfRule):
        return [s for item in rule.items for s in _rule_selectors(item)]
    return []


def student_term(audit: ExtractedAudit, state: StudentState) -> StudentTerm:
    by_id = {r.req_id: r for r in audit.requirements}
    titles = {r.req_id: r.title for r in audit.requirements}
    groups = {s.parent_id for s in state.requirements if s.parent_id}
    targets: dict[str, RequirementTarget] = {}
    for status in state.requirements:
        if status.state != "open" or status.req_id in groups:
            continue  # a group is satisfied through its child requirements
        req = by_id[status.req_id]
        selectors, excluded = parse_still_needed(req.still_needed_text)
        needed, unit = needed_amount(req.still_needed_text)
        if not selectors and isinstance(req.rule, UnparsedRule):
            selectors, excluded = parse_still_needed(req.rule.text)
            needed, unit = needed_amount(req.rule.text)
        if not selectors:
            selectors = _rule_selectors(req.rule)
            if isinstance(req.rule, CourseListRule):
                needed, unit = req.rule.count, req.rule.count_unit
        if selectors:
            targets[req.req_id] = RequirementTarget(
                title=display_title(req.req_id, titles),
                selectors=tuple(selectors),
                excluded=tuple(excluded),
                needed=needed,
                unit=unit,  # type: ignore[arg-type]
            )
    return StudentTerm(
        counted_courses=state.counted_courses,
        unplannable_courses=state.unplannable_courses,
        open_requirements=targets,
        standing=standing_from(audit.student.class_standing),  # type: ignore[arg-type]
    )
