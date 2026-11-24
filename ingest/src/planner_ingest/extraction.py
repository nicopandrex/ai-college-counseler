"""Typed model of the extraction output defined in docs/audit-extraction-prompt.md."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from planner_ingest.config import RequirementStatus

RULE_DEPTH = 4  # structured outputs reject recursive schemas; nesting is unrolled this deep


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseListRule(_Model):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["course_list"]
    count: float
    count_unit: Literal["courses", "credits"]
    from_: list[str] = Field(alias="from")


class AllOfRule(_Model):
    kind: Literal["all_of"]
    items: list[Rule]


class AnyOfRule(_Model):
    kind: Literal["any_of"]
    items: list[Rule]


class CreditTotalRule(_Model):
    kind: Literal["credit_total"]
    count: float
    constraints_text: str | None


class GpaRule(_Model):
    kind: Literal["gpa"]
    min: float
    scope_text: str | None


class UnparsedRule(_Model):
    kind: Literal["unparsed"]
    text: str


Rule = Annotated[
    CourseListRule | AllOfRule | AnyOfRule | CreditTotalRule | GpaRule | UnparsedRule,
    Field(discriminator="kind"),
]


AllOfRule.model_rebuild()
AnyOfRule.model_rebuild()


class Program(_Model):
    type: Literal["major", "minor", "certificate", "degree"]
    name: str
    degree: str | None


class Student(_Model):
    catalog_year: str | None
    programs: list[Program]
    class_standing: str | None
    overall_credits_earned: float | None
    overall_credits_in_progress: float | None
    overall_gpa: float | None


class CourseTaken(_Model):
    code: str
    title: str | None
    credits: float | None
    grade: str | None
    term: str | None
    status: Literal["complete", "in_progress", "preregistered"]
    applied_to_req_ids: list[str]
    source_quote: str


class CourseNotUsed(_Model):
    code: str
    reason_text: str | None
    source_quote: str


class Requirement(_Model):
    req_id: str
    title: str
    program: str | None
    status: RequirementStatus
    rule: Rule
    still_needed_text: str | None
    satisfied_by: list[str]
    has_wildcard: bool
    confidence: float = Field(ge=0, le=1)
    source_quote: str


class AuditException(_Model):
    text: str
    applies_to_req_id: str | None
    source_quote: str


class ExtractedAudit(_Model):
    student: Student
    courses_taken: list[CourseTaken]
    courses_not_used: list[CourseNotUsed]
    requirements: list[Requirement]
    exceptions: list[AuditException]
    parse_notes: list[str]


# -- JSON schema for structured output ------------------------------------------------------


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


STR: dict[str, Any] = {"type": "string"}
NUM: dict[str, Any] = {"type": "number"}
STRS: dict[str, Any] = {"type": "array", "items": STR}


def _rule_defs() -> dict[str, Any]:
    leaves = [
        _obj(
            {
                "kind": {"const": "course_list"},
                "count": NUM,
                "count_unit": {"enum": ["courses", "credits"]},
                "from": STRS,
            }
        ),
        _obj({"kind": {"const": "credit_total"}, "count": NUM, "constraints_text": _nullable(STR)}),
        _obj({"kind": {"const": "gpa"}, "min": NUM, "scope_text": _nullable(STR)}),
        _obj({"kind": {"const": "unparsed"}, "text": STR}),
    ]
    defs: dict[str, Any] = {"rule_0": {"anyOf": leaves}}
    for depth in range(1, RULE_DEPTH + 1):
        child = {"type": "array", "items": {"$ref": f"#/$defs/rule_{depth - 1}"}}
        defs[f"rule_{depth}"] = {
            "anyOf": [
                *leaves,
                _obj({"kind": {"const": "all_of"}, "items": child}),
                _obj({"kind": {"const": "any_of"}, "items": child}),
            ]
        }
    return defs


def llm_output_schema() -> dict[str, Any]:
    program = _obj(
        {
            "type": {"enum": ["major", "minor", "certificate", "degree"]},
            "name": STR,
            "degree": _nullable(STR),
        }
    )
    student = _obj(
        {
            "catalog_year": _nullable(STR),
            "programs": {"type": "array", "items": program},
            "class_standing": _nullable(STR),
            "overall_credits_earned": _nullable(NUM),
            "overall_credits_in_progress": _nullable(NUM),
            "overall_gpa": _nullable(NUM),
        }
    )
    course = _obj(
        {
            "code": STR,
            "title": _nullable(STR),
            "credits": _nullable(NUM),
            "grade": _nullable(STR),
            "term": _nullable(STR),
            "status": {"enum": ["complete", "in_progress", "preregistered"]},
            "applied_to_req_ids": STRS,
            "source_quote": STR,
        }
    )
    not_used = _obj({"code": STR, "reason_text": _nullable(STR), "source_quote": STR})
    requirement = _obj(
        {
            "req_id": STR,
            "title": STR,
            "program": _nullable(STR),
            "status": {"enum": ["complete", "in_progress", "incomplete", "unknown"]},
            "rule": {"$ref": f"#/$defs/rule_{RULE_DEPTH}"},
            "still_needed_text": _nullable(STR),
            "satisfied_by": STRS,
            "has_wildcard": {"type": "boolean"},
            "confidence": NUM,
            "source_quote": STR,
        }
    )
    exception = _obj({"text": STR, "applies_to_req_id": _nullable(STR), "source_quote": STR})
    schema = _obj(
        {
            "student": student,
            "courses_taken": {"type": "array", "items": course},
            "courses_not_used": {"type": "array", "items": not_used},
            "requirements": {"type": "array", "items": requirement},
            "exceptions": {"type": "array", "items": exception},
            "parse_notes": STRS,
        }
    )
    schema["$defs"] = _rule_defs()
    return schema
