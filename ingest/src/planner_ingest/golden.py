"""Golden files: hand-verified ground truth for an audit, and the comparison against them.

The M1 done-bar compares, for every requirement: status and count_unit; for every course:
code, grade, credits (plus title, term and status). A draft golden is generated from the
deterministic layout so the owner only corrects it; it is never produced by the LLM under test.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from planner_ingest.config import RequirementStatus, SchoolConfig
from planner_ingest.extraction import CourseListRule, CreditTotalRule, ExtractedAudit, Rule
from planner_ingest.ids import requirement_ids
from planner_ingest.layout import AuditLayout
from planner_ingest.validate import ICON_TO_STATUS, deterministic_courses

CountUnit = Literal["courses", "credits"]
ROW_UNIT = re.compile(r"\b\d+(?:\.\d+)? (?:\w+ )?(credits?|class(?:es)?|courses?)\b", re.IGNORECASE)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenRequirement(_Model):
    req_id: str
    title: str
    page: int
    status: RequirementStatus
    count_unit: CountUnit | None
    document_text: str  # for the reviewer; not compared


class GoldenCourse(_Model):
    code: str
    title: str | None
    grade: str | None
    credits: float | None
    term: str | None
    status: Literal["complete", "in_progress", "preregistered"]


class Golden(_Model):
    reviewed: bool  # set true by the owner after hand-correction
    requirements: list[GoldenRequirement]
    courses: list[GoldenCourse]


def _draft_unit(content: str, label: str) -> CountUnit | None:
    """The unit the document text counts in; None when absent or when both units appear."""
    for text in (content, label):
        units = {
            "credits" if m.group(1).lower().startswith("credit") else "courses"
            for m in ROW_UNIT.finditer(text)
        }
        if units:
            return units.pop() if len(units) == 1 else None
    return None


def draft_golden(layout: AuditLayout, config: SchoolConfig) -> Golden:
    ids = requirement_ids(layout)
    requirements: list[GoldenRequirement] = []
    for block in layout.blocks:
        if block.status_text:
            requirements.append(
                GoldenRequirement(
                    req_id=ids[block.block_id],
                    title=block.title,
                    page=block.page,
                    status=config.status_words[block.status_text],
                    count_unit=None,
                    document_text=" ".join(block.info),
                )
            )
        for row in block.rows:
            if not row.icon_status:
                continue
            requirements.append(
                GoldenRequirement(
                    req_id=ids[row.row_id],
                    title=row.label,
                    page=row.page,
                    status=ICON_TO_STATUS.get(row.icon_status, "unknown"),
                    count_unit=_draft_unit(" ".join(row.content), row.label),
                    document_text=row.text,
                )
            )
    courses = [
        GoldenCourse(
            **c.model_dump(include={"code", "title", "grade", "credits", "term", "status"})
        )
        for c in deterministic_courses(layout, config, {})
    ]
    return Golden(reviewed=False, requirements=requirements, courses=courses)


def rule_unit(rule: Rule) -> CountUnit | None:
    if isinstance(rule, CourseListRule):
        return rule.count_unit
    if isinstance(rule, CreditTotalRule):
        return "credits"
    return None


def compare(audit: ExtractedAudit, golden: Golden) -> list[str]:
    """Every difference between an extraction and the golden, as readable lines."""
    diffs: list[str] = []
    got = {r.req_id: r for r in audit.requirements}
    want = {r.req_id: r for r in golden.requirements}
    diffs += [f"missing requirement {rid}" for rid in want.keys() - got.keys()]
    diffs += [f"unexpected requirement {rid}" for rid in got.keys() - want.keys()]
    for rid in sorted(want.keys() & got.keys()):
        if got[rid].status != want[rid].status:
            diffs.append(f"{rid}: status {got[rid].status!r} != {want[rid].status!r}")
        unit = rule_unit(got[rid].rule)
        if want[rid].count_unit is not None and unit != want[rid].count_unit:
            diffs.append(f"{rid}: count_unit {unit!r} != {want[rid].count_unit!r}")

    def key(course: Any) -> tuple[str, str | None]:
        return (course.code, course.term)

    got_courses = {key(c): c for c in audit.courses_taken}
    want_courses = {key(c): c for c in golden.courses}
    diffs += [f"missing course {k}" for k in want_courses.keys() - got_courses.keys()]
    diffs += [f"unexpected course {k}" for k in got_courses.keys() - want_courses.keys()]
    for k in sorted(want_courses.keys() & got_courses.keys(), key=str):
        for name in ("title", "grade", "credits", "status"):
            a, b = getattr(got_courses[k], name), getattr(want_courses[k], name)
            if a != b:
                diffs.append(f"course {k}: {name} {a!r} != {b!r}")
    return diffs
