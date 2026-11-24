"""`planner` CLI.

planner build-term --term 202701         raw SOC scrape -> committed data/uvm/202701/
planner prereqs --term 202701 [--sample N]   parse new prerequisite notes (LLM), saved
planner solve --audit A.pdf --spec S.json [--fail CS 3240 ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from planner_ingest.bridge import student_term
from planner_ingest.pipeline import PURPOSE, extract_audit
from planner_ingest.state import Assumptions, derive_state
from planner_ingest.uvm.parse import default_credit_range, load_capabilities
from planner_ingest.uvm.prereqs import PURPOSE as PREREQ_PURPOSE
from planner_ingest.uvm.prereqs import parse_prereqs
from planner_ingest.uvm.store import build_term, load_answers, load_notes, load_term, save_prereqs
from planner_llm import LLMGateway
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
    print(
        f"{len(notes)} courses with prerequisite notes: {len(trees)} parsed, {len(review)} to review"
    )
    return 0


def cmd_solve(args: argparse.Namespace) -> int:
    gateway = LLMGateway.from_env(PURPOSE)
    extraction = extract_audit(args.audit, gateway)
    if gateway.usage["live_calls"]:
        print(gateway.usage_summary(), file=sys.stderr)
    policy = "per_course" if args.fail else "assume_pass"
    state = derive_state(
        extraction.audit, Assumptions(in_progress_policy=policy, failed_courses=tuple(args.fail))
    )
    student = student_term(extraction.audit, state)
    if args.standing:  # the student's own statement for the target term overrides the audit
        student = student.model_copy(update={"standing": args.standing})
    term = load_term(args.term)
    context = ValidationContext(
        course_codes=frozenset(term.courses),
        requirement_ids=frozenset(r.req_id for r in extraction.audit.requirements),
        unplannable_courses=student.unplannable_courses,
        capabilities=SchoolCapabilities(unavailable=load_capabilities()),
        default_credit_range=default_credit_range(),
    )
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
    solve.add_argument("--term", default="202701")
    solve.add_argument("--fail", nargs="*", default=[], help="in-progress courses to assume failed")
    solve.add_argument(
        "--standing",
        choices=["freshman", "sophomore", "junior", "senior", "graduate"],
        help="your class standing for the target term (default: the audit's)",
    )
    args = parser.parse_args(argv)
    commands = {"build-term": cmd_build_term, "prereqs": cmd_prereqs, "solve": cmd_solve}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
