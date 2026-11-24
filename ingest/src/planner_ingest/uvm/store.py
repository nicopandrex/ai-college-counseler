"""Committed, derived UVM data under data/uvm/, so nothing is re-scraped or re-parsed (paid)
just because a container is recycled.

  data/uvm/<term>/term.json            courses + sections (built from the raw scrape)
  data/uvm/<term>/prereq_notes.json    course -> SOC prerequisite note text
  data/uvm/<term>/prereqs.json         usable prerequisite trees
  data/uvm/<term>/prereq_review.json   doubtful ones (kept out of the solver)
  data/uvm/prereq_answers.json         note text -> parsed answer, reused across terms
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from planner_ingest.uvm.owner_rules import apply_owner_rules
from planner_ingest.uvm.parse import parse_term
from planner_ingest.uvm.prereqs import has_prereq_text, prereq_notes
from planner_solver.domain import Prereq, TermData, UnparsedPrereq

RAW = Path("data/raw/uvm")
DATA = Path("data/uvm")
TREES = TypeAdapter(dict[str, Prereq | None])
_SEASON_MONTH = {"SP": "01", "SU": "06", "FA": "09"}  # UVM's SOC term codes (202701 = Spring 2027)


def soc_term(term: str) -> str:
    """'2027SP' (the spec's term code) -> '202701' (UVM's Schedule of Courses code)."""
    return term[:4] + _SEASON_MONTH[term[4:]]


def build_term(srcdb: str, raw: Path = RAW, data: Path = DATA) -> TermData:
    """Raw scrape -> committed term.json and prerequisite note text."""
    term, _ = parse_term(raw / srcdb, srcdb)
    notes = {}
    for path in sorted((raw / srcdb / "details").glob("*.json")):
        details = json.loads(path.read_text())
        text = prereq_notes(details)
        if has_prereq_text(text):
            notes[details["code"]] = text
    out = data / srcdb
    out.mkdir(parents=True, exist_ok=True)
    (out / "term.json").write_text(term.model_dump_json())
    (out / "prereq_notes.json").write_text(json.dumps(notes, indent=1, sort_keys=True) + "\n")
    return term


def load_notes(srcdb: str, data: Path = DATA) -> dict[str, str]:
    return json.loads((data / srcdb / "prereq_notes.json").read_text())


def load_answers(data: Path = DATA) -> dict[str, dict[str, Any]]:
    path = data / "prereq_answers.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_prereqs(
    srcdb: str,
    trees: dict[str, Prereq | None],
    review: list[dict[str, str]],
    answers: dict[str, dict[str, Any]],
    data: Path = DATA,
) -> None:
    out = data / srcdb
    (out / "prereqs.json").write_text(TREES.dump_json(trees, indent=1).decode() + "\n")
    (out / "prereq_review.json").write_text(json.dumps(review, indent=1) + "\n")
    (data / "prereq_answers.json").write_text(json.dumps(answers, indent=1, sort_keys=True) + "\n")


def load_term(srcdb: str, data: Path = DATA) -> TermData:
    path = data / srcdb / "term.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `planner build-term --term {srcdb}`")
    term = TermData.model_validate_json(path.read_text())
    trees_path = data / srcdb / "prereqs.json"
    if not trees_path.exists():
        return term.model_copy(update={"courses": apply_owner_rules(term.courses)})
    trees = TREES.validate_json(trees_path.read_text())
    review_path = data / srcdb / "prereq_review.json"
    for item in json.loads(review_path.read_text()) if review_path.exists() else []:
        # doubtful and not usable: unknown, never "no prerequisite"
        trees.setdefault(item["code"], UnparsedPrereq(kind="unparsed", text=item["notes"]))
    courses = {
        code: c.model_copy(update={"prereq": trees.get(code)}) for code, c in term.courses.items()
    }
    return term.model_copy(update={"courses": apply_owner_rules(courses), "prereqs_loaded": True})
