"""Audit + UVM term data -> a ready ChatSession. Shared by the CLI and the web API."""

from __future__ import annotations

import re
from pathlib import Path

from planner_chat.session import ChatSession, StudentFacts
from planner_chat.translator import PURPOSE as TRANSLATE
from planner_chat.translator import TranslatorContext
from planner_ingest.bridge import student_term
from planner_ingest.extraction import ExtractedAudit
from planner_ingest.pipeline import PURPOSE, extract_audit
from planner_ingest.state import Assumptions, derive_state
from planner_ingest.uvm.parse import default_credit_range, load_capabilities, preferred_credit_range
from planner_ingest.uvm.store import load_term, soc_term
from planner_llm import LLMGateway
from planner_solver.domain import StudentTerm, TermData
from planner_solver.validation import SchoolCapabilities, ValidationContext

OUT_OF_SCOPE_LOG = Path(".planner/out_of_scope.jsonl")


def read_audit(pdf: Path, gateway: LLMGateway | None = None) -> ExtractedAudit:
    return extract_audit(pdf, gateway or LLMGateway.from_env(PURPOSE)).audit


def derive(audit: ExtractedAudit, failed: tuple[str, ...], standing: str | None) -> StudentTerm:
    policy = "per_course" if failed else "assume_pass"
    assumptions = Assumptions(in_progress_policy=policy, failed_courses=failed)
    student = student_term(audit, derive_state(audit, assumptions))
    if standing:  # the student's own statement for the target term overrides the audit
        student = student.model_copy(update={"standing": standing})
    return student


def validation_context(
    term: TermData, audit: ExtractedAudit, student: StudentTerm
) -> ValidationContext:
    instructors: dict[str, set[str]] = {}
    for section in term.sections:
        instructors.setdefault(section.course, set()).update(section.instructors)
    return ValidationContext(
        course_codes=frozenset(term.courses),
        requirement_ids=frozenset(r.req_id for r in audit.requirements),
        unplannable_courses=student.unplannable_courses,
        capabilities=SchoolCapabilities(unavailable=load_capabilities()),
        default_credit_range=default_credit_range(),
        preferred_credit_range=preferred_credit_range(),
        course_status={c.code: c.status for c in audit.courses_taken},
        instructors={code: frozenset(names) for code, names in instructors.items()},
    )


def facts(audit: ExtractedAudit) -> StudentFacts:
    s = audit.student
    return StudentFacts(
        credits_earned=s.overall_credits_earned,
        credits_in_progress=s.overall_credits_in_progress,
        standing=re.sub(r"^\d+\s*-\s*", "", s.class_standing or "") or None,  # "03 - Junior"
        in_progress=tuple(
            sorted({c.code for c in audit.courses_taken if c.status == "in_progress"})
        ),
    )


def open_chat(
    audit: ExtractedAudit,
    term_code: str = "2027SP",
    standing: str | None = None,
    failed: tuple[str, ...] = (),
    gateway: LLMGateway | None = None,
    out_of_scope_log: Path | None = OUT_OF_SCOPE_LOG,
) -> ChatSession:
    term = load_term(soc_term(term_code))
    student = derive(audit, failed, standing)
    blocks = {r.req_id: r.title for r in audit.requirements if "." not in r.req_id}
    context = TranslatorContext(
        target_term=term_code,
        open_requirements=[
            (rid, f"{blocks.get(rid.split('.')[0], '')} › {t.title}")
            for rid, t in student.open_requirements.items()
        ],
        catalog=sorted((c.code, c.title) for c in term.courses.values()),
        in_progress=sorted(
            {(c.code, c.title or c.code) for c in audit.courses_taken if c.status == "in_progress"}
        ),
    )

    def what_if(extra: tuple[str, ...]) -> tuple[StudentTerm, ValidationContext]:
        changed = derive(audit, tuple(sorted({*failed, *extra})), standing)
        return changed, validation_context(term, audit, changed)

    return ChatSession(
        context,
        term,
        student,
        validation_context(term, audit, student),
        gateway or LLMGateway.from_env(TRANSLATE),
        out_of_scope_log,
        facts=facts(audit),
        what_if=what_if,
    )
