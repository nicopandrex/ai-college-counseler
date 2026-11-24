"""Validation layer between the LLM and the solver (docs/constraint-spec-reference.md).

Rule 0: the raw spec must satisfy constraint-spec.schema.json exactly (the contract).
Rules 1-8 as in the reference doc. Errors block solving; the chat layer explains them.
A cleaned spec comes back with normalised course codes, unsupported constraints moved to
out_of_scope, and auto-generated clarifications for low-confidence constraints.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import jsonschema
from pydantic import ValidationError

from planner_solver.spec import (
    PLAN_ONLY,
    Clarification,
    Constraint,
    ConstraintSpec,
    OutOfScope,
    minutes,
    parse_params,
)

TERM_ONLY = frozenset(
    {
        "no_earlier_than",
        "no_later_than",
        "free_day",
        "free_block",
        "max_days_on_campus",
        "max_consecutive_classes",
        "gap_between_classes",
        "compactness",
        "instructor_preference",
        "modality",
        "section_size",
        "campus",
        "travel_time",
        "open_seats_only",
        "max_consecutive_labs",
        "max_labs_per_day",
    }
)
LOW_CONFIDENCE = 0.7
MAX_QUESTIONS = 2
COURSE_FIELDS = {
    "include_course": "course",
    "exclude_course": "course",
    "instructor_preference": "course",
}
_CODE = re.compile(r"^([A-Za-z]{2,5})\s*-?\s*(\d{4}[A-Za-z]?)$")


def contract_schema() -> dict[str, Any]:
    text = (
        resources.files("planner_solver.contract")
        .joinpath("constraint-spec.schema.json")
        .read_text()
    )
    return json.loads(text)


@dataclass(frozen=True)
class SchoolCapabilities:
    """Constraint types whose data the school can't provide: type -> reason shown to the user."""

    unavailable: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationContext:
    course_codes: frozenset[str]
    requirement_ids: frozenset[str]  # this student's requirements
    unplannable_courses: frozenset[str]  # already completed, in progress or registered
    capabilities: SchoolCapabilities = SchoolCapabilities()


@dataclass(frozen=True)
class Issue:
    rule: int
    message: str
    constraint_id: str | None = None


@dataclass
class ValidationResult:
    spec: ConstraintSpec | None
    errors: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def canonical_course(text: str) -> str | None:
    match = _CODE.match(text.strip())
    return f"{match.group(1).upper()} {match.group(2).upper()}" if match else None


def _check_course(con: Constraint, ctx: ValidationContext, result: ValidationResult) -> None:
    key = COURSE_FIELDS.get(con.type)
    value = con.params.get(key) if key else None
    if not value:
        return
    code = canonical_course(value)
    if code is None or code not in ctx.course_codes:
        close = difflib.get_close_matches(
            code or value.upper(), sorted(ctx.course_codes), n=3, cutoff=0.8
        )
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        result.errors.append(Issue(1, f"{value!r} is not a course in the catalog.{hint}", con.id))
        return
    if code != value:
        con.params[key] = code
        result.notes.append(f"{con.id}: read {value!r} as {code}")
    wants_it = con.type == "include_course" or (
        con.type == "instructor_preference" and con.params.get("polarity") == "include"
    )
    if wants_it and code in ctx.unplannable_courses:
        result.errors.append(
            Issue(1, f"{code} is already completed, in progress or registered", con.id)
        )


def _contradictions(constraints: list[Constraint]) -> list[Issue]:
    hard = [c for c in constraints if c.enforcement == "hard"]
    issues: list[Issue] = []

    def days(c: Constraint) -> set[str]:
        return set(c.params.get("days") or "MTWRFSU")

    for c in hard:
        p = c.params
        if (
            c.type in ("credit_range", "course_count_range", "credits_per_term")
            and p["min"] > p["max"]
        ):
            issues.append(Issue(6, f"minimum {p['min']} is above maximum {p['max']}", c.id))
        if c.type == "free_block" and minutes(p["start"]) >= minutes(p["end"]):
            issues.append(
                Issue(6, f"free block {p['start']}-{p['end']} ends before it starts", c.id)
            )
    for a in hard:
        for b in hard:
            if a.type == "no_earlier_than" and b.type == "no_later_than" and days(a) & days(b):
                if minutes(a.params["time"]) >= minutes(b.params["time"]):
                    start, end = a.params["time"], b.params["time"]
                    msg = f"no class before {start} and none after {end} leaves no time"
                    issues.append(Issue(6, msg + f" ({a.id}, {b.id})", a.id))
            if a.type == "include_course" and b.type == "exclude_course":
                if a.params["course"] == b.params["course"]:
                    msg = f"{a.params['course']} is both required ({a.id}) and excluded ({b.id})"
                    issues.append(Issue(6, msg, a.id))
    return issues


def _question(con: Constraint) -> Clarification:
    said = f"“{con.source_text}”" if con.source_text else f"the {con.type.replace('_', ' ')} rule"
    if con.weight_source in ("inferred", "default"):
        return Clarification(
            question=f"How important is {said} to you, 1–5?",
            kind="weight_check",
            constraint_id=con.id,
            options=["1", "2", "3", "4", "5"],
        )
    detail = ", ".join(f"{k}={v}" for k, v in con.params.items())
    return Clarification(
        question=f"Quick check on {said}: did you mean {con.type} ({detail})?",
        kind="ambiguity",
        constraint_id=con.id,
        options=["Yes", "No"],
    )


def validate_spec(raw: dict[str, Any], ctx: ValidationContext) -> ValidationResult:
    try:
        jsonschema.validate(raw, contract_schema())
    except jsonschema.ValidationError as exc:
        return ValidationResult(None, [Issue(0, f"does not match the contract: {exc.message}")])
    try:
        spec = ConstraintSpec.model_validate(raw)
    except ValidationError as exc:  # stricter than the schema only where pydantic types are
        return ValidationResult(None, [Issue(0, f"does not match the contract: {exc}")])

    result = ValidationResult(spec)
    if (spec.mode == "term") != (spec.target_term is not None):
        result.errors.append(Issue(4, "target_term is required in term mode and only there"))

    kept: list[Constraint] = []
    for con in spec.constraints:
        if spec.mode == "term" and con.type in PLAN_ONLY:
            result.errors.append(Issue(3, f"{con.type} only applies to multi-term plans", con.id))
            continue
        if spec.mode == "plan" and con.type in TERM_ONLY:
            result.errors.append(
                Issue(3, f"{con.type} only applies to a single term's schedule", con.id)
            )
            continue
        try:
            parse_params(con)
        except (ValidationError, ValueError) as exc:
            result.errors.append(Issue(5, f"bad params for {con.type}: {exc}", con.id))
            continue
        reason = ctx.capabilities.unavailable.get(con.type)
        if reason:
            spec.out_of_scope.append(
                OutOfScope(request=f"{con.type}: {reason}", user_text=con.source_text)
            )
            result.notes.append(f"{con.id}: dropped ({reason})")
            continue
        _check_course(con, ctx, result)
        if con.type == "satisfy_requirement":
            unknown = [r for r in con.params["req_ids"] if r not in ctx.requirement_ids]
            if unknown:
                result.errors.append(
                    Issue(2, f"not one of your requirements: {', '.join(unknown)}", con.id)
                )
        kept.append(con)
    spec.constraints = kept

    if not result.errors:
        result.errors.extend(_contradictions(kept))

    asked = {q.constraint_id for q in spec.clarifications}
    for con in kept:
        if len(spec.clarifications) >= MAX_QUESTIONS:
            break
        if con.confidence is not None and con.confidence < LOW_CONFIDENCE and con.id not in asked:
            spec.clarifications.append(_question(con))
    return result
