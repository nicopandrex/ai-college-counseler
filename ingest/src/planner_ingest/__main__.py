"""CLI: `python -m planner_ingest {layout,extract,draft-golden} <audit.pdf> [--out FILE]`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from planner_ingest.config import load_school_config
from planner_ingest.golden import draft_golden
from planner_ingest.layout import parse_layout
from planner_ingest.pipeline import PURPOSE, extract_audit
from planner_ingest.render import render_for_llm
from planner_llm import LLMGateway


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planner_ingest")
    parser.add_argument("command", choices=["layout", "extract", "draft-golden"])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--school", default="uvm")
    parser.add_argument("--out", type=Path, help="write the extraction report JSON here")
    args = parser.parse_args(argv)

    config = load_school_config(args.school)
    if args.command == "layout":
        sys.stdout.write(render_for_llm(parse_layout(args.pdf, config)))
        return 0
    if args.command == "draft-golden":
        golden = draft_golden(parse_layout(args.pdf, config), config)
        _emit(golden.model_dump_json(indent=2), args.out)
        return 0

    result = extract_audit(args.pdf, LLMGateway.from_env(PURPOSE), args.school)
    _emit(json.dumps(result.report(), indent=2), args.out)
    errors = sum(1 for issue in result.issues if issue.severity == "error")
    review = len(result.report()["needs_review"])
    print(f"{len(result.issues)} issues ({errors} errors); {review} need review", file=sys.stderr)
    return 0


def _emit(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text + "\n")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
