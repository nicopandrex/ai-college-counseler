"""Natural language -> constraint spec (contract instance). Validation happens afterwards (M5).

Strict structured output can't express the contract's free-form `params` object, and a
per-type union exceeds Gemini's schema limits, so the model returns `params_json` (a JSON
object as a string). It's decoded here and checked by validation rule 0 / rule 5.

The same call also says what kind of message it was (`intent`, outside the contract): only a
scheduling request changes the spec; greetings and questions are answered by the chat layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from planner_llm import JsonRequest, LLMGateway
from planner_solver.spec import PARAMS

PURPOSE = "translate"
INTENTS = ("schedule", "question", "greeting", "thanks")
TOPICS = (
    "remaining_requirements",
    "credits_earned",
    "requirement_details",
    "course_info",
    "course_options",
    "what_if_fail",
    "instructor_opinion",
    "other",
)


@dataclass(frozen=True)
class TranslatorContext:
    target_term: str  # e.g. "2027SP"
    open_requirements: list[tuple[str, str]]  # (req_id, title)
    catalog: list[tuple[str, str]]  # (code, title)
    programs: list[tuple[str, str]] = field(default_factory=list)  # (program_id, name)
    in_progress: list[tuple[str, str]] = field(default_factory=list)  # (code, title) this term


@dataclass
class Translation:
    spec: dict[str, Any]  # a contract instance (to be validated)
    problems: list[str]  # constraints dropped because params_json wasn't a JSON object
    intent: str = "schedule"
    topic: str | None = None  # for questions
    courses: list[str] = field(default_factory=list)  # courses a question is about
    requirements: list[str] = field(default_factory=list)  # requirement ids it is about
    subjects: list[str] = field(default_factory=list)  # subject codes it is about ("ECON")


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
    string = {"type": "string"}
    constraint = _obj(
        {
            "id": string,
            "type": {"enum": sorted(PARAMS)},
            "params_json": string,
            "enforcement": {"enum": ["hard", "soft"]},
            "weight": {"type": "integer"},
            "weight_source": {"enum": ["stated", "inferred", "default", "user_confirmed"]},
            "confidence": {"type": "number"},
            "source_text": string,
            "data_dependency": {"enum": ["reliable", "estimated", "may_be_missing"]},
        }
    )
    clarification = _obj(
        {
            "question": string,
            "kind": {"enum": ["weight_check", "ambiguity", "missing_info", "tradeoff"]},
            "constraint_id": _nullable(string),
            "options": {"type": "array", "items": string},
            "blocking": {"type": "boolean"},
        }
    )
    return _obj(
        {
            "intent": {"enum": list(INTENTS)},
            "question_topic": _nullable({"enum": list(TOPICS)}),
            "question_courses": {"type": "array", "items": string},
            "question_requirements": {"type": "array", "items": string},
            "question_subjects": {"type": "array", "items": string},
            "spec_version": {"enum": ["0.1"]},
            "mode": {"enum": ["term", "plan"]},
            "target_term": _nullable(string),
            "restatement": string,
            "constraints": {"type": "array", "items": constraint},
            "clarifications": {"type": "array", "items": clarification},
            "out_of_scope": {
                "type": "array",
                "items": _obj({"request": string, "user_text": string}),
            },
        }
    )


def system_prompt() -> str:
    folder = resources.files("planner_chat.prompts")
    return folder.joinpath("translator.md").read_text(encoding="utf-8") + folder.joinpath(
        "constraint-spec-reference.md"
    ).read_text(encoding="utf-8")


HISTORY_TURNS = 6  # recent messages the model sees, to resolve "those", "that class"
HISTORY_CHARS = 700  # per message


def user_message(
    message: str,
    context: TranslatorContext,
    prior: dict[str, Any] | None,
    history: list[tuple[str, str]] | None = None,
) -> str:
    lines = [f"TARGET TERM: {context.target_term}", "", "OPEN REQUIREMENTS:"]
    lines += [f"- {rid}: {title}" for rid, title in context.open_requirements]
    if context.programs:
        lines += ["", "PROGRAMS:"] + [f"- {pid}: {name}" for pid, name in context.programs]
    if context.in_progress:
        lines += ["", "IN-PROGRESS COURSES:"]
        lines += [f"- {code} — {title}" for code, title in context.in_progress]
    lines += ["", "CATALOG:"] + [f"{code} — {title}" for code, title in context.catalog]
    if prior is not None:
        lines += ["", "PRIOR SPEC:", json.dumps(prior, indent=1)]
    if history:
        lines += ["", "RECENT CONVERSATION:"]
        for who, text in history[-HISTORY_TURNS:]:
            clipped = text if len(text) <= HISTORY_CHARS else text[:HISTORY_CHARS] + " …"
            lines.append(f"{who}: {clipped}")
    lines += ["", "MESSAGE:", message]
    return "\n".join(lines) + "\n"


def _decode_params(text: Any) -> Any:
    """A JSON object; a stray quote or whitespace after a complete one is a known model slip."""
    if not isinstance(text, str):
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(text.strip())
    except json.JSONDecodeError:
        return None
    return value if not text.strip()[end:].strip(" \n\"'") else None


def to_contract(raw: dict[str, Any]) -> Translation:
    """The model's output -> a contract instance (params decoded, nulls dropped)."""
    problems: list[str] = []
    constraints = []
    for item in raw.get("constraints", []):
        params = _decode_params(item.get("params_json"))
        if not isinstance(params, dict):
            problems.append(
                f"{item.get('id')}: params_json is not a JSON object: {item.get('params_json')!r}"
            )
            continue
        constraint = {k: v for k, v in item.items() if k != "params_json"}
        constraints.append({**constraint, "params": params})
    clarifications = [
        {k: v for k, v in q.items() if v is not None} for q in raw.get("clarifications", [])
    ]
    spec: dict[str, Any] = {
        "spec_version": "0.1",
        "mode": raw["mode"],
        "restatement": raw["restatement"],
        "constraints": constraints,
        "clarifications": clarifications,
        "out_of_scope": raw.get("out_of_scope", []),
    }
    if raw.get("target_term"):
        spec["target_term"] = raw["target_term"]
    return Translation(
        spec,
        problems,
        intent=raw.get("intent") or "schedule",
        topic=raw.get("question_topic"),
        courses=list(raw.get("question_courses") or []),
        requirements=list(raw.get("question_requirements") or []),
        subjects=list(raw.get("question_subjects") or []),
    )


def translate(
    message: str,
    context: TranslatorContext,
    gateway: LLMGateway,
    prior: dict[str, Any] | None = None,
    effort: str = "medium",
    history: list[tuple[str, str]] | None = None,
) -> Translation:
    request = JsonRequest(
        purpose=PURPOSE,
        system=system_prompt(),
        user=user_message(message, context, prior, history),
        schema=output_schema(),
        max_tokens=16000,
        effort=effort,
    )
    return to_contract(gateway.complete_json(request))
