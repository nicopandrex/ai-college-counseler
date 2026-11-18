"""derive_state: parsed audit -> the solver's student state. Pure and deterministic, no LLM.

Per docs/audit-extraction-prompt.md ("Downstream: the derived planning state"):
- in-progress (and preregistered) work counts toward prerequisites and coverage unless the
  policy says it fails; requirements met only that way are `provisionally_satisfied`;
- `earned` (current standing) and `earned_plus_in_progress` (plan mode) are kept apart;
- min-grade requirements met by ungraded work carry `pending_grade_risk`;
- preregistered and already-counted courses are unplannable.
Choose-one groups (an `any_of` requirement whose children are alternatives, e.g. majors with
tracks) keep only the alternative the student is following: the one with courses applied.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from planner_ingest.extraction import (
    AnyOfRule,
    CreditTotalRule,
    ExtractedAudit,
    Requirement,
    Rule,
    UnparsedRule,
)

RequirementState = Literal["satisfied", "provisionally_satisfied", "open", "not_applicable"]
CHOOSE_ONE = re.compile(r"\bChoose from 1 of the following\b", re.I)  # DegreeWorks wording
MIN_GRADE = re.compile(r"\b[A-D][+-]? or (better|higher)\b|\bminimum (course )?grade\b", re.I)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Assumptions(_Model):
    in_progress_policy: Literal["assume_pass", "assume_fail", "per_course"] = "assume_pass"
    failed_courses: tuple[str, ...] = ()  # used by per_course: these in-progress courses fail
    min_grade_pending_policy: Literal["assume_met", "assume_not_met"] = "assume_met"


class Credits(_Model):
    earned: float  # completed work only: what to show as current standing
    earned_plus_in_progress: float  # + in-progress work assumed passed: what plan mode uses
    preregistered: float  # next term's registrations: never part of current standing


class RequirementStatus(_Model):
    req_id: str
    title: str
    parent_id: str | None
    recorded_status: str  # what the audit says
    state: RequirementState  # what planning assumes
    applied_courses: tuple[str, ...]
    pending_grade_risk: bool
    still_needed_text: str | None
    source_quote: str
    needs_review: bool


class StudentState(_Model):
    assumptions: Assumptions
    credits: Credits
    counted_courses: frozenset[str]  # satisfy prerequisites in planning
    unplannable_courses: frozenset[str]  # the solver must never propose these
    requirements: tuple[RequirementStatus, ...]
    warnings: tuple[str, ...] = Field(default=())

    @property
    def open_requirement_ids(self) -> list[str]:
        return [r.req_id for r in self.requirements if r.state == "open"]


def _fails(code: str, assumptions: Assumptions) -> bool:
    if assumptions.in_progress_policy == "assume_fail":
        return True
    if assumptions.in_progress_policy == "per_course":
        return code in assumptions.failed_courses
    return False


def _rule_texts(rule: Rule) -> list[str]:
    if isinstance(rule, UnparsedRule):
        return [rule.text]
    if isinstance(rule, CreditTotalRule) and rule.constraints_text:
        return [rule.constraints_text]
    return []


def _has_min_grade(req: Requirement) -> bool:
    texts = [req.title, req.still_needed_text or "", *_rule_texts(req.rule)]
    return any(MIN_GRADE.search(t) for t in texts)


def _is_choice_group(req: Requirement) -> bool:
    """Alternatives where only one must be completed (e.g. a major's tracks)."""
    texts = [req.still_needed_text or "", *_rule_texts(req.rule)]
    return isinstance(req.rule, AnyOfRule) or any(CHOOSE_ONE.search(t) for t in texts)


def _parents(ids: set[str]) -> dict[str, str | None]:
    """Hierarchy from the structure-derived req_ids: a.b.c's parent is a.b."""
    out: dict[str, str | None] = {}
    for rid in ids:
        parent = rid.rsplit(".", 1)[0] if "." in rid else None
        out[rid] = parent if parent in ids else None
    return out


def derive_state(audit: ExtractedAudit, assumptions: Assumptions | None = None) -> StudentState:
    assumptions = assumptions or Assumptions()
    statuses: dict[str, set[str]] = {}
    for c in audit.courses_taken:
        statuses.setdefault(c.code, set()).add(c.status)

    def passes(code: str) -> bool:
        """Counts as earned for planning (completed, or ungraded and assumed passed)."""
        s = statuses.get(code, set())
        return "complete" in s or (
            bool(s & {"in_progress", "preregistered"}) and not _fails(code, assumptions)
        )

    failed = {
        c.code
        for c in audit.courses_taken
        if c.status == "in_progress" and _fails(c.code, assumptions)
    }
    counted = frozenset(code for code in statuses if passes(code))
    credits = Credits(
        earned=sum(c.credits or 0 for c in audit.courses_taken if c.status == "complete"),
        earned_plus_in_progress=sum(
            c.credits or 0
            for c in audit.courses_taken
            if c.status == "complete" or (c.status == "in_progress" and c.code not in failed)
        ),
        preregistered=sum(
            c.credits or 0 for c in audit.courses_taken if c.status == "preregistered"
        ),
    )

    by_id = {r.req_id: r for r in audit.requirements}
    parent_of = _parents(set(by_id))
    children: dict[str, list[str]] = {}
    for rid, parent in parent_of.items():
        if parent:
            children.setdefault(parent, []).append(rid)

    state: dict[str, RequirementState] = {}
    risk: dict[str, bool] = {}
    for req in audit.requirements:
        ungraded = [c for c in req.satisfied_by if "complete" not in statuses.get(c, set())]
        risky = bool(ungraded) and _has_min_grade(req)
        risk[req.req_id] = risky
        if req.status == "complete":
            state[req.req_id] = "satisfied"
        elif req.status == "in_progress":
            lost = any(not passes(c) for c in req.satisfied_by)
            grade_unmet = risky and assumptions.min_grade_pending_policy == "assume_not_met"
            state[req.req_id] = "open" if lost or grade_unmet else "provisionally_satisfied"
        else:
            state[req.req_id] = "open"

    # A requirement cannot be met while a required part is open (any_of needs only one part).
    for rid in sorted(by_id, key=lambda r: -r.count(".")):
        kids = children.get(rid, [])
        if not kids or state[rid] == "open":
            continue
        kid_states = [state[k] for k in kids]
        if _is_choice_group(by_id[rid]):
            if all(s == "open" for s in kid_states):
                state[rid] = "open"
        elif "open" in kid_states:
            state[rid] = "open"

    warnings: list[str] = []
    for rid, req in by_id.items():
        kids = children.get(rid, [])
        if not _is_choice_group(req) or len(kids) < 2:
            continue
        progress = {k: _applied_in_subtree(k, by_id, children) for k in kids}
        best = max(progress.values())
        leaders = [k for k, n in progress.items() if n == best]
        if best == 0 or len(leaders) > 1:
            warnings.append(
                f"{rid}: cannot tell which alternative is being followed; all kept open"
            )
            continue
        for alternative in kids:
            if alternative != leaders[0]:
                for node in _subtree(alternative, children):
                    state[node] = "not_applicable"

    requirements = tuple(
        RequirementStatus(
            req_id=r.req_id,
            title=r.title,
            parent_id=parent_of[r.req_id],
            recorded_status=r.status,
            state=state[r.req_id],
            applied_courses=tuple(r.satisfied_by),
            pending_grade_risk=risk[r.req_id],
            still_needed_text=r.still_needed_text,
            source_quote=r.source_quote,
            needs_review=r.confidence < 0.8 or r.status == "unknown",
        )
        for r in audit.requirements
    )
    unplannable = frozenset(
        code for code, s in statuses.items() if "preregistered" in s or code in counted
    )
    return StudentState(
        assumptions=assumptions,
        credits=credits,
        counted_courses=counted,
        unplannable_courses=unplannable,
        requirements=requirements,
        warnings=tuple(warnings),
    )


def _subtree(root: str, children: dict[str, list[str]]) -> list[str]:
    nodes, stack = [], [root]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(children.get(node, []))
    return nodes


def _applied_in_subtree(
    root: str, by_id: dict[str, Requirement], children: dict[str, list[str]]
) -> int:
    return sum(len(by_id[n].satisfied_by) for n in _subtree(root, children))
