"""SOC comment prose -> prerequisite trees (LLM), with a review queue for doubtful ones.

Only courses whose comments mention prerequisites, standing or permission are sent; a course
the model skips is asked about once more. Every doubtful course goes to the review queue:
- a tree whose only problem is an `unparsed` part is still used: that part evaluates as
  "unknown", so it can never make a prerequisite look met;
- an ambiguous, invalid or malformed-code tree, or a skipped course, is kept out of the solver
  (the caller marks it unknown).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from typing import Any

from pydantic import TypeAdapter, ValidationError

from planner_llm import JsonRequest, LLMGateway
from planner_solver.domain import AllPrereq, AnyPrereq, CoursePrereq, Prereq, UnparsedPrereq

PURPOSE = "prereq_parse"
BATCH_SIZE = 25
WORKERS = 6
MENTIONS = re.compile(
    r"pre-?req|co-?req|standing|permission|consent of|minimum grade|or better", re.I
)
CODE = re.compile(r"^[A-Z]{2,5} \d{4}[A-Z]?$")
TAG = re.compile(r"<[^>]+>")
_PREREQ = TypeAdapter(Prereq)


def prereq_notes(details: dict[str, Any]) -> str:
    return " ".join(TAG.sub(" ", details.get("clssnotes") or "").split())


def has_prereq_text(notes: str) -> bool:
    return bool(MENTIONS.search(notes))


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def output_schema() -> dict[str, Any]:
    """Flat node list (children by id): any nesting depth, without a recursive schema."""
    node = _obj(
        {
            "id": {"type": "string"},
            "kind": {"enum": ["and", "or", "course", "standing", "permission", "unparsed"]},
            "children": {"type": "array", "items": {"type": "string"}},
            "code": _nullable({"type": "string"}),
            "min_grade": _nullable({"type": "string"}),
            "concurrent_ok": {"type": "boolean"},
            "minimum": _nullable({"enum": ["sophomore", "junior", "senior", "graduate"]}),
            "text": _nullable({"type": "string"}),
        }
    )
    entry = _obj(
        {
            "code": {"type": "string"},
            "nodes": {"type": "array", "items": node},
            "root": _nullable({"type": "string"}),
            "ambiguous": {"type": "boolean"},
            "note": _nullable({"type": "string"}),
        }
    )
    return _obj({"courses": {"type": "array", "items": entry}})


class _BadTree(ValueError):
    pass


def build_tree(nodes: list[dict[str, Any]], root: str | None) -> Prereq | None:
    """Rebuild the nested tree; dangling ids, cycles and kind/field mismatches are errors."""
    if root is None:
        return None
    by_id = {n["id"]: n for n in nodes}

    def build(nid: str, path: frozenset[str]) -> dict[str, Any]:
        if nid not in by_id or nid in path:
            raise _BadTree(f"node {nid!r} is missing or cyclic")
        n = by_id[nid]
        kind = n["kind"]
        if kind in ("and", "or"):
            if not n["children"]:
                raise _BadTree(f"{kind} node {nid!r} has no children")
            return {"kind": kind, "items": [build(c, path | {nid}) for c in n["children"]]}
        fields = {
            "course": ("code", "min_grade", "concurrent_ok"),
            "standing": ("minimum",),
            "permission": ("text",),
            "unparsed": ("text",),
        }[kind]
        out = {"kind": kind, **{f: n[f] for f in fields}}
        if kind == "course" and out["min_grade"] is None:
            del out["min_grade"]
        return out

    return _PREREQ.validate_python(build(root, frozenset()))


def _problems(tree: Prereq) -> list[str]:
    if isinstance(tree, CoursePrereq):
        return [] if CODE.match(tree.code) else [f"malformed course code {tree.code!r}"]
    if isinstance(tree, UnparsedPrereq):
        return [f"unparsed: {tree.text}"]
    if isinstance(tree, AllPrereq | AnyPrereq):
        return [p for item in tree.items for p in _problems(item)]
    return []


def parse_prereqs(
    notes: dict[str, str], gateway: LLMGateway, batch_size: int = BATCH_SIZE, workers: int = WORKERS
) -> tuple[dict[str, Prereq | None], list[dict[str, str]]]:
    """(trees for the courses that passed every check, review queue)."""
    system = resources.files("planner_ingest.prompts").joinpath("prereq_parse.md").read_text()
    codes = sorted(notes)
    batches = [codes[i : i + batch_size] for i in range(0, len(codes), batch_size)]

    def ask(batch: list[str]) -> list[dict[str, Any]]:
        user = "\n".join(f"{code} | {notes[code]}" for code in batch)
        request = JsonRequest(
            purpose=PURPOSE,
            system=system,
            user=user,
            schema=output_schema(),
            max_tokens=32000,
            effort="low",  # bulk job: thinking tokens are billed as output
        )
        return gateway.complete_json(request)["courses"]

    def collect(groups: list[list[str]]) -> dict[str, dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return {
                a["code"]: a
                for result in pool.map(ask, groups)
                for a in result
                if a["code"] in notes
            }

    answers = collect(batches)
    skipped = [code for code in codes if code not in answers]
    answers |= collect([skipped[i : i + batch_size] for i in range(0, len(skipped), batch_size)])

    trees: dict[str, Prereq | None] = {}
    review: list[dict[str, str]] = []
    for code in codes:
        answer = answers.get(code)
        if answer is None:
            review.append(
                {"code": code, "notes": notes[code], "reason": "not returned by the model"}
            )
            continue
        try:
            tree = build_tree(answer["nodes"], answer["root"])
        except (_BadTree, ValidationError) as exc:
            review.append({"code": code, "notes": notes[code], "reason": f"invalid tree: {exc}"})
            continue
        problems = ([answer.get("note") or "flagged ambiguous"] if answer["ambiguous"] else []) + (
            _problems(tree) if tree else []
        )
        if problems:
            review.append({"code": code, "notes": notes[code], "reason": "; ".join(problems)})
        if all(p.startswith("unparsed:") for p in problems):
            trees[code] = tree
    return trees, review
