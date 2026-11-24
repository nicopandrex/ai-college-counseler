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
from planner_solver.term import instructor_matches

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
DEFAULT_LOAD_NOTE = "no credit load stated, so I'm using full time ({low:g}–{high:g} credits)"
TAKEN = {  # audit course statuses
    "complete": "you've already completed {code}",
    "in_progress": "you're taking {code} now",
    "preregistered": "you're already registered for {code}",
}
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
        .read_text(encoding="utf-8")
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
    default_credit_range: tuple[float, float] | None = None  # full-time band if none stated
    preferred_credit_range: tuple[float, float] | None = None  # soft default inside that band
    course_status: dict[str, str] = field(default_factory=dict)  # code -> completed/in_progress/…
    instructors: dict[str, frozenset[str]] = field(default_factory=dict)  # course -> who teaches


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
        result.notes.append(f"read “{value}” as {code}")
    wants_it = con.type == "include_course" or (
        con.type == "instructor_preference" and con.params.get("polarity") == "include"
    )
    if wants_it and code in ctx.unplannable_courses:
        status = TAKEN.get(ctx.course_status.get(code, ""), "{code} is already taken or registered")
        result.errors.append(Issue(1, status.format(code=code), con.id))


def _check_instructor(con: Constraint, ctx: ValidationContext, result: ValidationResult) -> None:
    """The named instructor must teach this term (and the course, if one is given)."""
    if con.type != "instructor_preference" or not ctx.instructors:
        return
    name, course = con.params["name"], con.params.get("course")
    pool = (
        ctx.instructors.get(course, frozenset())
        if course
        else frozenset().union(*ctx.instructors.values())
    )
    if any(instructor_matches(name, who) for who in pool):
        return
    everyone = sorted(frozenset().union(*ctx.instructors.values()))
    if course and any(instructor_matches(name, who) for who in everyone):
        message = f"{name} doesn't teach {course} this term"
    else:
        lasts = {who.split(",")[0].split()[-1].casefold(): who for who in everyone}
        wanted = name.split(",")[0].split()[-1].casefold()
        close = [
            lasts[m] for m in difflib.get_close_matches(wanted, sorted(lasts), n=3, cutoff=0.7)
        ]
        hint = f" Did you mean {' or '.join(close)}?" if close else ""
        message = f"no section this term is taught by anyone named {name}.{hint}"
    if con.params["polarity"] == "exclude":
        result.notes.append(f"{message}, so “not with {name}” is already true")
    else:
        result.errors.append(Issue(1, message, con.id))


def _complete_range(con: Constraint, ctx: ValidationContext, result: ValidationResult) -> None:
    """'3 classes max' or 'at least 15 credits': fill the unstated end from the defaults."""
    p = con.params
    if con.type == "credit_range" and ctx.default_credit_range:
        low, high = ctx.default_credit_range
        filled = {"min": low, "max": high}
    elif con.type == "course_count_range":
        filled = {"min": 1}
    else:
        return
    missing = {k: v for k, v in filled.items() if k not in p}
    if missing and ("min" in p or "max" in p):
        p.update(missing)
        unit = "credits" if con.type == "credit_range" else "classes"
        said = f"“{con.source_text}”" if con.source_text else "that"
        result.notes.append(f"read {said} as {p['min']:g}–{p['max']:g} {unit}")


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
        _complete_range(con, ctx, result)
        try:
            parse_params(con)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'params'}: {e['msg']}" for e in exc.errors()
            )
            result.errors.append(Issue(5, f"bad params for {con.type} ({problems})", con.id))
            continue
        except ValueError as exc:
            result.errors.append(Issue(5, f"bad params for {con.type} ({exc})", con.id))
            continue
        reason = ctx.capabilities.unavailable.get(con.type)
        if reason:  # said once, through out_of_scope
            spec.out_of_scope.append(OutOfScope(request=reason, user_text=con.source_text))
            continue
        _check_course(con, ctx, result)
        _check_instructor(con, ctx, result)
        if con.type == "satisfy_requirement":
            unknown = [r for r in con.params["req_ids"] if r not in ctx.requirement_ids]
            if unknown:
                result.errors.append(
                    Issue(2, f"not one of your requirements: {', '.join(unknown)}", con.id)
                )
        kept.append(con)
    spec.constraints = kept
    # the full-time band holds unless the student sets a hard load; a stated preference
    # ("around 12-14") works inside it
    loads = [con for con in kept if con.type == "credit_range"]
    stated = any(con.enforcement == "hard" for con in loads)
    if spec.mode == "term" and not stated and ctx.default_credit_range:
        low, high = ctx.default_credit_range
        default = {
            "id": "default_credits",
            "type": "credit_range",
            "params": {"min": low, "max": high},
            "enforcement": "hard",
            "weight": 3,
            "weight_source": "default",
            "confidence": 1.0,
            "source_text": "",
        }
        kept.append(Constraint.model_validate(default))
        result.notes.append(DEFAULT_LOAD_NOTE.format(low=low, high=high))
        if ctx.preferred_credit_range and not loads:
            low, high = ctx.preferred_credit_range
            if any(c.type == "difficulty_load" and c.params.get("target") == "light" for c in kept):
                high = min(high, low + 1)  # a light load: the low end of full time
            preferred = {
                "id": "default_load_preference",
                "type": "credit_range",
                "params": {"min": low, "max": high},
                "enforcement": "soft",
                "weight": 3,
                "weight_source": "default",
                "confidence": 1.0,
                "source_text": "a typical load",
            }
            kept.append(Constraint.model_validate(preferred))

    if not result.errors:
        result.errors.extend(_contradictions(kept))

    asked = {q.constraint_id for q in spec.clarifications}
    for con in kept:
        if len(spec.clarifications) >= MAX_QUESTIONS:
            break
        if con.confidence is not None and con.confidence < LOW_CONFIDENCE and con.id not in asked:
            spec.clarifications.append(_question(con))
    return result
