"""SOC comment prose -> prerequisite trees (LLM), with a review queue for doubtful ones.

Only courses whose comments mention prerequisites, standing or permission are sent. A tree is
queued for human review (and kept out of the solver) if the model flags it ambiguous, it
contains an `unparsed` node, a course code is malformed, or the model skipped the course.
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
TREE_DEPTH = 2  # or -> and -> course; deeper notes come back as `unparsed`
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
    leaves = [
        _obj(
            {
                "kind": {"const": "course"},
                "code": {"type": "string"},
                "min_grade": _nullable({"type": "string"}),
                "concurrent_ok": {"type": "boolean"},
            }
        ),
        _obj(
            {
                "kind": {"const": "standing"},
                "minimum": {"enum": ["sophomore", "junior", "senior", "graduate"]},
            }
        ),
        _obj({"kind": {"const": "permission"}, "text": {"type": "string"}}),
        _obj({"kind": {"const": "unparsed"}, "text": {"type": "string"}}),
    ]
    defs: dict[str, Any] = {"node_0": {"anyOf": leaves}}
    for depth in range(1, TREE_DEPTH + 1):
        child = {"type": "array", "items": {"$ref": f"#/$defs/node_{depth - 1}"}}
        defs[f"node_{depth}"] = {
            "anyOf": [
                *leaves,
                _obj({"kind": {"const": "and"}, "items": child}),
                _obj({"kind": {"const": "or"}, "items": child}),
            ]
        }
    entry = _obj(
        {
            "code": {"type": "string"},
            "prereq": _nullable({"$ref": f"#/$defs/node_{TREE_DEPTH}"}),
            "ambiguous": {"type": "boolean"},
            "note": _nullable({"type": "string"}),
        }
    )
    schema = _obj({"courses": {"type": "array", "items": entry}})
    schema["$defs"] = defs
    return schema


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
            effort="medium",
        )
        return gateway.complete_json(request)["courses"]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        answers = {
            a["code"]: a for result in pool.map(ask, batches) for a in result if a["code"] in notes
        }

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
            tree = None if answer["prereq"] is None else _PREREQ.validate_python(answer["prereq"])
        except ValidationError as exc:
            review.append({"code": code, "notes": notes[code], "reason": f"invalid tree: {exc}"})
            continue
        problems = ([answer.get("note") or "flagged ambiguous"] if answer["ambiguous"] else []) + (
            _problems(tree) if tree else []
        )
        if problems:
            review.append({"code": code, "notes": notes[code], "reason": "; ".join(problems)})
        else:
            trees[code] = tree
    return trees, review
