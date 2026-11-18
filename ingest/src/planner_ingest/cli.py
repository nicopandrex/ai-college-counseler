"""`planner` CLI.

planner prereqs --term 202701            parse SOC prerequisite notes once (LLM), cached
planner solve --audit A.pdf --spec S.json [--fail CS 3240 ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from planner_ingest.bridge import student_term
from planner_ingest.pipeline import PURPOSE, extract_audit
from planner_ingest.state import Assumptions, derive_state
from planner_ingest.uvm.owner_rules import apply_owner_rules
from planner_ingest.uvm.parse import load_capabilities, parse_term
from planner_ingest.uvm.prereqs import PURPOSE as PREREQ_PURPOSE
from planner_ingest.uvm.prereqs import has_prereq_text, parse_prereqs, prereq_notes
from planner_llm import LLMGateway
from planner_solver.domain import Prereq, TermData, UnparsedPrereq
from planner_solver.present import render_result
from planner_solver.term import solve_term
from planner_solver.validation import SchoolCapabilities, ValidationContext, validate_spec

RAW = Path("data/raw/uvm")
_TREES = TypeAdapter(dict[str, Prereq | None])


def load_term(srcdb: str, raw: Path = RAW) -> TermData:
    term, _ = parse_term(raw / srcdb, srcdb)
    term = term.model_copy(update={"courses": apply_owner_rules(term.courses)})
    trees_path = raw / srcdb / "prereqs.json"
    if not trees_path.exists():
        return term
    trees = _TREES.validate_json(trees_path.read_text())
    review_path = raw / srcdb / "prereq_review.json"
    review = json.loads(review_path.read_text()) if review_path.exists() else []
    for item in review:  # doubtful and not usable: unknown, never "no prerequisite"
        trees.setdefault(item["code"], UnparsedPrereq(kind="unparsed", text=item["notes"]))
    courses = apply_owner_rules(
        {
            code: course.model_copy(update={"prereq": trees.get(code)})
            for code, course in term.courses.items()
        }
    )
    return term.model_copy(update={"courses": courses, "prereqs_loaded": True})


def cmd_prereqs(args: argparse.Namespace) -> int:
    cache = RAW / args.term
    notes = {}
    for path in sorted((cache / "details").glob("*.json")):
        details = json.loads(path.read_text())
        text = prereq_notes(details)
        if has_prereq_text(text):
            notes[details["code"]] = text
    trees, review = parse_prereqs(notes, LLMGateway.from_env(PREREQ_PURPOSE))
    (cache / "prereqs.json").write_text(_TREES.dump_json(trees, indent=1).decode())
    (cache / "prereq_review.json").write_text(json.dumps(review, indent=1))
    summary = f"{len(trees)} parsed, {len(review)} to review"
    print(f"{len(notes)} courses with prerequisite notes: {summary}")
    return 0


def cmd_solve(args: argparse.Namespace) -> int:
    extraction = extract_audit(args.audit, LLMGateway.from_env(PURPOSE))
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
    pre = sub.add_parser("prereqs", help="parse SOC prerequisite notes (LLM, cached)")
    pre.add_argument("--term", default="202701")
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
    return cmd_prereqs(args) if args.command == "prereqs" else cmd_solve(args)


if __name__ == "__main__":
    sys.exit(main())
