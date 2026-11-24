"""`planner` CLI.

planner build-term --term 202701         raw SOC scrape -> committed data/uvm/202701/
planner prereqs --term 202701 [--sample N]   parse new prerequisite notes (LLM), saved
planner solve --audit A.pdf --spec S.json [--term 2027SP] [--fail CS 3240 ...] [--standing senior]
planner chat --audit A.pdf [--term 2027SP] [--standing senior] [--script messages.txt]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from planner_chat.session import ChatSession, StudentFacts
from planner_chat.translator import PURPOSE as TRANSLATE
from planner_chat.translator import TranslatorContext
from planner_ingest.bridge import student_term
from planner_ingest.extraction import ExtractedAudit
from planner_ingest.pipeline import PURPOSE, extract_audit
from planner_ingest.state import Assumptions, derive_state
from planner_ingest.uvm.parse import default_credit_range, load_capabilities, preferred_credit_range
from planner_ingest.uvm.prereqs import PURPOSE as PREREQ_PURPOSE
from planner_ingest.uvm.prereqs import parse_prereqs
from planner_ingest.uvm.store import (
    build_term,
    load_answers,
    load_notes,
    load_term,
    save_prereqs,
    soc_term,
)
from planner_llm import LLMGateway
from planner_solver.domain import StudentTerm, TermData
from planner_solver.present import render_result
from planner_solver.term import solve_term
from planner_solver.validation import SchoolCapabilities, ValidationContext, validate_spec


def cmd_build_term(args: argparse.Namespace) -> int:
    term = build_term(args.term)
    print(
        f"saved {len(term.courses)} courses, {len(term.sections)} sections to data/uvm/{args.term}/"
    )
    return 0


def cmd_prereqs(args: argparse.Namespace) -> int:
    notes = load_notes(args.term)
    if args.sample:  # check cost and quality on a few courses before a bulk run
        notes = dict(sorted(notes.items())[: args.sample])
    gateway = LLMGateway.from_env(PREREQ_PURPOSE)
    trees, review, answers = parse_prereqs(notes, gateway, known=load_answers())
    print(gateway.usage_summary(), file=sys.stderr)
    if not args.sample:
        save_prereqs(args.term, trees, review, answers)
    outcome = f"{len(trees)} parsed, {len(review)} to review"
    print(f"{len(notes)} courses with prerequisite notes: {outcome}")
    return 0


OUT_OF_SCOPE_LOG = Path(".planner/out_of_scope.jsonl")


def _student(args: argparse.Namespace) -> tuple[ExtractedAudit, StudentTerm]:
    gateway = LLMGateway.from_env(PURPOSE)
    extraction = extract_audit(args.audit, gateway)
    if gateway.usage["live_calls"]:
        print(gateway.usage_summary(), file=sys.stderr)
    return extraction.audit, _derive(extraction.audit, tuple(args.fail), args.standing)


def _derive(audit: ExtractedAudit, failed: tuple[str, ...], standing: str | None) -> StudentTerm:
    policy = "per_course" if failed else "assume_pass"
    assumptions = Assumptions(in_progress_policy=policy, failed_courses=failed)
    student = student_term(audit, derive_state(audit, assumptions))
    if standing:  # the student's own statement for the target term overrides the audit
        student = student.model_copy(update={"standing": standing})
    return student


def _validation(term: TermData, audit: ExtractedAudit, student: StudentTerm) -> ValidationContext:
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


def _facts(audit: ExtractedAudit) -> StudentFacts:
    s = audit.student
    return StudentFacts(
        credits_earned=s.overall_credits_earned,
        credits_in_progress=s.overall_credits_in_progress,
        standing=re.sub(r"^\d+\s*-\s*", "", s.class_standing or "") or None,  # "03 - Junior"
        in_progress=tuple(
            sorted({c.code for c in audit.courses_taken if c.status == "in_progress"})
        ),
    )


def cmd_chat(args: argparse.Namespace) -> int:
    audit, student = _student(args)
    term = load_term(soc_term(args.term))
    blocks = {r.req_id: r.title for r in audit.requirements if "." not in r.req_id}
    context = TranslatorContext(
        target_term=args.term,
        open_requirements=[
            (rid, f"{blocks.get(rid.split('.')[0], '')} › {t.title}")
            for rid, t in student.open_requirements.items()
        ],
        catalog=sorted((c.code, c.title) for c in term.courses.values()),
        in_progress=sorted(
            {(c.code, c.title or c.code) for c in audit.courses_taken if c.status == "in_progress"}
        ),
    )

    def what_if(failed: tuple[str, ...]) -> tuple[StudentTerm, ValidationContext]:
        changed = _derive(audit, tuple(sorted({*args.fail, *failed})), args.standing)
        return changed, _validation(term, audit, changed)

    chat = ChatSession(
        context,
        term,
        student,
        _validation(term, audit, student),
        LLMGateway.from_env(TRANSLATE),
        OUT_OF_SCOPE_LOG,
        facts=_facts(audit),
        what_if=what_if,
    )
    messages = args.script.read_text().splitlines() if args.script else None
    print(f"Planning {args.term}. Tell me what you want; /spec shows your requests, /quit exits.")
    while True:
        if messages is not None:
            if not messages:
                break
            message = messages.pop(0)
            print(f"\nyou> {message}")
        else:
            try:
                message = input("\nyou> ")
            except EOFError:
                break
        if message.strip() in ("/quit", "/exit"):
            break
        if message.strip():
            print(chat.handle(message))
    print(chat.gateway.usage_summary(), file=sys.stderr)
    return 0


def cmd_solve(args: argparse.Namespace) -> int:
    audit, student = _student(args)
    term = load_term(soc_term(args.term))
    context = _validation(term, audit, student)
    checked = validate_spec(json.loads(args.spec.read_text()), context)
    for note in checked.notes:
        print(f"note: {note}")
    if not checked.ok or checked.spec is None:
        for issue in checked.errors:
            print(f"can't use this request (rule {issue.rule}): {issue.message}")
        return 1
    result = solve_term(checked.spec, term, student)
    print(render_result(result, checked.spec, term, student))
    for q in checked.spec.clarifications:
        print(f"question: {q.question}" + (f" [{' / '.join(q.options)}]" if q.options else ""))
    for item in checked.spec.out_of_scope:
        print(f"can't do yet: {item.request}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planner")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-term", help="raw SOC scrape -> committed data/uvm/<term>/")
    build.add_argument("--term", default="202701")
    pre = sub.add_parser("prereqs", help="parse SOC prerequisite notes (LLM, cached)")
    pre.add_argument("--term", default="202701")
    pre.add_argument("--sample", type=int, help="parse only the first N courses (cost check)")
    solve = sub.add_parser("solve", help="solve one term for an audit and a constraint spec")
    solve.add_argument("--audit", type=Path, required=True)
    solve.add_argument("--spec", type=Path, required=True)
    solve.add_argument("--term", default="2027SP")
    solve.add_argument("--fail", nargs="*", default=[], help="in-progress courses to assume failed")
    solve.add_argument(
        "--standing",
        choices=["freshman", "sophomore", "junior", "senior", "graduate"],
        help="your class standing for the target term (default: the audit's)",
    )
    chat = sub.add_parser("chat", help="chat about one term's schedule for an audit")
    chat.add_argument("--audit", type=Path, required=True)
    chat.add_argument("--term", default="2027SP")
    chat.add_argument("--fail", nargs="*", default=[], help="in-progress courses to assume failed")
    chat.add_argument(
        "--standing", choices=["freshman", "sophomore", "junior", "senior", "graduate"]
    )
    chat.add_argument("--script", type=Path, help="read messages from a file (one per line)")
    args = parser.parse_args(argv)
    commands = {
        "build-term": cmd_build_term,
        "prereqs": cmd_prereqs,
        "solve": cmd_solve,
        "chat": cmd_chat,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
