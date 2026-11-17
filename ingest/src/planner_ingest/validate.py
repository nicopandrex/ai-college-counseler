"""Deterministic post-processing and validation of the LLM's extraction.

The LLM output is checked against the deterministic layout, never trusted blindly:
- every requirement is anchored to a document row (or block) through its source_quote;
- req_ids are replaced with structure-derived ids (stable across re-uploads);
- courses_taken is rebuilt from the parsed course lines; the LLM's list is only compared;
- status, count_unit, satisfied_by, codes, coverage and credit sums are cross-checked.
A failed check is reported as an Issue and caps that requirement's confidence, so it is
routed to human review instead of being silently accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from planner_ingest.config import IconStatus, RequirementStatus, SchoolConfig
from planner_ingest.extraction import (
    AllOfRule,
    AnyOfRule,
    CourseListRule,
    CourseTaken,
    ExtractedAudit,
    Requirement,
    Rule,
)
from planner_ingest.ids import requirement_ids
from planner_ingest.layout import AuditLayout, Block, CourseLine, Row

LOW_CONFIDENCE = 0.8
FLAGGED_CONFIDENCE_CAP = 0.5
ICON_TO_STATUS: dict[IconStatus, RequirementStatus] = {
    "complete": "complete",
    "incomplete": "incomplete",
    "nearly_complete": "incomplete",
    "in_progress": "in_progress",
}
RULE_CODE = re.compile(
    r"^(@|[A-Z]{2,5}) (@|\d@|\d{2}@|\d{3}@|[0-9X]{4}[A-Z]?|\d{4}:\d{4})$"
    r"|^@ @$"
    r"|^@ @ with attribute = [A-Z0-9]+$"  # DegreeWorks' own attribute-selector notation
)
STRUCTURAL_TAG = re.compile(r"^(BLOCK|ROW|COURSE)\s+|\[(icon|block status|no icon)[^\]]*\]\s*")
COURSES_UNIT = re.compile(r"\b\d+(\.\d+)? (class|classes|course|courses)\b", re.IGNORECASE)
CREDITS_UNIT = re.compile(r"\b\d+(\.\d+)? (credit|credits)\b", re.IGNORECASE)
CREDITS_APPLIED = re.compile(r"Credits applied: (\d+(?:\.\d+)?)")
CLASSES_APPLIED = re.compile(r"Classes applied: (\d+)")
CATALOG_YEAR = re.compile(r"Catalog year: (\d{4}-\d{4})")

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    message: str
    req_id: str | None = None


@dataclass(frozen=True)
class Anchor:
    key: str  # block_id or row_id
    block: Block
    row: Row | None


def normalize(text: str) -> str:
    return " ".join(text.replace("|", " ").split()).casefold()


def quote_text(quote: str) -> str:
    """A source_quote minus the renderer's own tags (BLOCK/ROW/COURSE, [icon: ...])."""
    return normalize(STRUCTURAL_TAG.sub("", quote.strip()))


def _candidates(layout: AuditLayout) -> list[tuple[Anchor, str, str]]:
    """(anchor, searchable text, label) for every block and row, in document order."""
    out: list[tuple[Anchor, str, str]] = []
    for block in layout.blocks:
        block_text = " ".join([block.title, block.status_text or "", *block.info])
        out.append(
            (Anchor(block.block_id, block, None), normalize(block_text), normalize(block.title))
        )
        for row in block.rows:
            out.append((Anchor(row.row_id, block, row), normalize(row.text), normalize(row.label)))
    return out


def anchor_requirements(audit: ExtractedAudit, layout: AuditLayout) -> list[Anchor | None]:
    """Match requirements to document locations by quote, then title, keeping document order."""
    candidates = _candidates(layout)
    claimed: set[str] = set()
    last = -1
    anchors: list[Anchor | None] = []
    for req in audit.requirements:
        quote, title = quote_text(req.source_quote), normalize(req.title)
        hits = [i for i, (_, text, _) in enumerate(candidates) if quote and quote in text]
        if not hits:
            hits = [i for i, (_, _, label) in enumerate(candidates) if title and label == title]
        if not hits:
            anchors.append(None)
            continue
        best = min(
            hits,
            key=lambda i: (
                candidates[i][0].key in claimed,
                i <= last,
                candidates[i][2] != title,
                i,
            ),
        )
        anchor = candidates[best][0]
        if anchor.key in claimed:
            anchors.append(None)
            continue
        claimed.add(anchor.key)
        last = best
        anchors.append(anchor)
    return anchors


def _course_status(course: CourseLine, config: SchoolConfig) -> str:
    if course.grade in config.preregistered_grades:
        return "preregistered"
    if course.in_progress_marker or course.grade in config.in_progress_grades:
        return "in_progress"
    return "complete"


def _rule_codes(rule: Rule) -> list[str]:
    if isinstance(rule, CourseListRule):
        return list(rule.from_)
    if isinstance(rule, AllOfRule | AnyOfRule):
        return [code for item in rule.items for code in _rule_codes(item)]
    return []


def _unit_in(text: str) -> str | None:
    has_courses, has_credits = bool(COURSES_UNIT.search(text)), bool(CREDITS_UNIT.search(text))
    if has_courses == has_credits:
        return None
    return "courses" if has_courses else "credits"


def _unique_courses(rows: list[Row]) -> dict[tuple[str, str], CourseLine]:
    unique: dict[tuple[str, str], CourseLine] = {}
    for row in rows:
        for course in row.courses:
            unique.setdefault((course.code, course.term), course)
    return unique


class _Checker:
    def __init__(self, layout: AuditLayout, config: SchoolConfig) -> None:
        self.layout = layout
        self.config = config
        self.issues: list[Issue] = []
        self.flagged: set[int] = set()  # indexes into requirements whose confidence gets capped

    def issue(
        self, code: str, message: str, req_id: str | None = None, severity: Severity = "warning"
    ) -> None:
        self.issues.append(Issue(code, severity, message, req_id))

    def flag(self, index: int, req: Requirement, code: str, message: str) -> None:
        """An issue with one extracted requirement: reported, and its confidence is capped."""
        self.issue(code, message, req.req_id, "error" if code == "no_anchor" else "warning")
        self.flagged.add(index)

    def check_requirement(self, index: int, req: Requirement, anchor: Anchor | None) -> None:
        if quote_text(req.source_quote) not in normalize(self.layout.full_text):
            self.flag(index, req, "quote_not_found", f"quote not in document: {req.source_quote!r}")
        if anchor is None:
            self.flag(index, req, "no_anchor", f"could not locate {req.title!r} in the document")
            return
        expected = self._expected_status(anchor)
        if expected is not None and req.status != expected:
            message = f"status {req.status!r} but the document marks it {expected!r}"
            self.flag(index, req, "status_mismatch", message)
        if anchor.row is not None and anchor.row.icon_status == "unknown":
            self.flag(index, req, "icon_unknown", "status icon color not recognised")
        if req.status == "complete" and req.still_needed_text:
            self.flag(
                index, req, "complete_but_still_needed", "complete, yet has still-needed text"
            )
        codes = _rule_codes(req.rule)
        for code in codes:
            if not RULE_CODE.match(code):
                self.flag(index, req, "malformed_course_code", f"rule course code {code!r}")
        if any("@" in code for code in codes) and not req.has_wildcard:
            self.flag(index, req, "wildcard_flag", "rule has '@' codes but has_wildcard is false")
        if anchor.row is not None:
            self._check_row(index, req, anchor.row)

    def _expected_status(self, anchor: Anchor) -> RequirementStatus | None:
        if anchor.row is not None:
            return ICON_TO_STATUS.get(anchor.row.icon_status) if anchor.row.icon_status else None
        return self.config.status_words.get(anchor.block.status_text or "")

    def _check_row(self, index: int, req: Requirement, row: Row) -> None:
        unit = _unit_in(" ".join(row.content)) or _unit_in(row.label)
        if unit and isinstance(req.rule, CourseListRule) and req.rule.count_unit != unit:
            message = f"rule counts {req.rule.count_unit} but the document counts {unit}"
            self.flag(index, req, "count_unit_mismatch", message)
        row_codes = {c.code for c in row.courses}
        if row_codes != set(req.satisfied_by):
            message = f"satisfied_by {sorted(req.satisfied_by)}, row lists {sorted(row_codes)}"
            self.flag(index, req, "satisfied_by_mismatch", message)
        statuses = {_course_status(c, self.config) for c in row.courses}
        if req.status == "complete" and statuses and statuses <= {"in_progress", "preregistered"}:
            message = "complete, but only in-progress courses apply"
            self.flag(index, req, "complete_only_in_progress", message)

    def check_coverage(self, anchors: list[Anchor | None], ids: dict[str, str]) -> None:
        anchored = {a.key for a in anchors if a is not None}
        for block in self.layout.blocks:
            if block.status_text and block.block_id not in anchored:
                message = f"block {block.title!r} was not extracted"
                self.issue("missing_requirement", message, ids[block.block_id], "error")
            for row in block.rows:
                if row.icon_status and row.row_id not in anchored:
                    message = f"row {row.label!r} (page {row.page}) was not extracted"
                    self.issue("missing_requirement", message, ids[row.row_id], "error")

    def check_courses(self, llm: list[CourseTaken], deterministic: list[CourseTaken]) -> None:
        ours = {(c.code, c.term): c for c in deterministic}
        theirs = {(c.code, c.term): c for c in llm}
        for code, term in theirs.keys() - ours.keys():
            message = f"LLM listed {code} ({term}), which is not a course row"
            self.issue("course_not_in_document", message, severity="error")
        for code, term in ours.keys() - theirs.keys():
            self.issue("course_missed_by_llm", f"LLM omitted {code} ({term})")
        for key in ours.keys() & theirs.keys():
            for name in ("title", "grade", "credits", "status"):
                doc, llm_value = getattr(ours[key], name), getattr(theirs[key], name)
                if doc != llm_value:
                    message = f"{key[0]} {name}: document {doc!r}, LLM {llm_value!r}"
                    self.issue("course_field_mismatch", message)

    def check_credit_sums(self) -> None:
        for position, block in enumerate(self.layout.blocks):
            courses = _unique_courses(block.rows)
            if not courses and position == 0:  # the degree block totals every course
                courses = _unique_courses(self.layout.rows)
            if not courses:
                continue
            info = " ".join(block.info)
            stated = CREDITS_APPLIED.search(info)
            total = sum(c.credits or 0 for c in courses.values())
            if stated and abs(float(stated.group(1)) - total) > 0.01:
                message = f"{block.title}: {stated.group(1)} credits applied, rows sum to {total:g}"
                self.issue("credit_sum_mismatch", message)
            classes = CLASSES_APPLIED.search(info)
            if classes and int(classes.group(1)) != len(courses):
                message = f"{block.title}: {classes.group(1)} classes applied, found {len(courses)}"
                self.issue("class_count_mismatch", message)

    def check_catalog_year(self, audit: ExtractedAudit) -> None:
        info = " ".join(i for b in self.layout.blocks for i in b.info)
        years = {m.group(1) for m in CATALOG_YEAR.finditer(info)}
        stated = audit.student.catalog_year
        if stated is not None and years and stated not in years:
            self.issue("catalog_year_mismatch", f"catalog_year {stated!r} not in {sorted(years)}")


def deterministic_courses(
    layout: AuditLayout, config: SchoolConfig, row_req_ids: dict[str, str]
) -> list[CourseTaken]:
    """courses_taken from parsed course lines; applied_to = requirements whose rows list it."""
    applied: dict[tuple[str, str], list[str]] = {}
    first: dict[tuple[str, str], CourseLine] = {}
    for row in layout.rows:
        for course in row.courses:
            key = (course.code, course.term)
            first.setdefault(key, course)
            req_id = row_req_ids.get(row.row_id)
            if req_id and req_id not in applied.setdefault(key, []):
                applied[key].append(req_id)
    return [
        CourseTaken(
            code=c.code,
            title=c.title or None,
            credits=c.credits,
            grade=c.grade or None,
            term=c.term,
            status=_course_status(c, config),  # type: ignore[arg-type]
            applied_to_req_ids=applied.get(key, []),
            source_quote=c.source_text,
        )
        for key, c in first.items()
    ]


def finalize(
    audit: ExtractedAudit, layout: AuditLayout, config: SchoolConfig
) -> tuple[ExtractedAudit, list[Issue]]:
    ids = requirement_ids(layout)
    anchors = anchor_requirements(audit, layout)
    checker = _Checker(layout, config)

    remap: dict[str, str] = {}
    requirements: list[Requirement] = []
    for index, (req, anchor) in enumerate(zip(audit.requirements, anchors, strict=True)):
        new_id = ids[anchor.key] if anchor else req.req_id
        remap.setdefault(req.req_id, new_id)
        requirements.append(req.model_copy(update={"req_id": new_id}))
        checker.check_requirement(index, requirements[-1], anchor)

    checker.check_coverage(anchors, ids)
    row_req_ids = {a.key: ids[a.key] for a in anchors if a is not None and a.row is not None}
    courses = deterministic_courses(layout, config, row_req_ids)
    checker.check_courses(audit.courses_taken, courses)
    checker.check_credit_sums()
    checker.check_catalog_year(audit)

    requirements = [
        r.model_copy(update={"confidence": min(r.confidence, FLAGGED_CONFIDENCE_CAP)})
        if i in checker.flagged
        else r
        for i, r in enumerate(requirements)
    ]
    exceptions = [
        e.model_copy(
            update={"applies_to_req_id": remap.get(e.applies_to_req_id, e.applies_to_req_id)}
        )
        if e.applies_to_req_id
        else e
        for e in audit.exceptions
    ]
    final = audit.model_copy(
        update={"requirements": requirements, "courses_taken": courses, "exceptions": exceptions}
    )
    return final, checker.issues


def review_items(audit: ExtractedAudit) -> list[Requirement]:
    """Requirements the user must confirm before the planner relies on them."""
    return [r for r in audit.requirements if r.confidence < LOW_CONFIDENCE]
