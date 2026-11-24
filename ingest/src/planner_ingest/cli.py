"""`planner` CLI.

planner build-term --term 202701         raw SOC scrape -> committed data/uvm/202701/
planner prereqs --term 202701 [--sample N]   parse new prerequisite notes (LLM), saved
planner solve --audit A.pdf --spec S.json [--term 2027SP] [--fail CS 3240 ...] [--standing senior]
planner chat --audit A.pdf [--term 2027SP] [--standing senior] [--script messages.txt]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from planner_ingest.chat_setup import derive, open_chat, read_audit, validation_context
from planner_ingest.extraction import ExtractedAudit
from planner_ingest.pipeline import PURPOSE
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
from planner_llm.envfile import load_env_file
from planner_solver.domain import StudentTerm
from planner_solver.present import render_result
from planner_solver.term import solve_term
from planner_solver.validation import validate_spec


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


def _student(args: argparse.Namespace) -> tuple[ExtractedAudit, StudentTerm]:
    gateway = LLMGateway.from_env(PURPOSE)
    audit = read_audit(args.audit, gateway)
    if gateway.usage["live_calls"]:
        print(gateway.usage_summary(), file=sys.stderr)
    return audit, derive(audit, tuple(args.fail), args.standing)


def cmd_chat(args: argparse.Namespace) -> int:
    audit, _ = _student(args)
    chat = open_chat(audit, args.term, args.standing, tuple(args.fail))
    messages = args.script.read_text(encoding="utf-8").splitlines() if args.script else None
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
    context = validation_context(term, audit, student)
    checked = validate_spec(json.loads(args.spec.read_text(encoding="utf-8")), context)
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
    load_env_file()
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
