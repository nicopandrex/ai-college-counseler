"""One chat conversation: message -> translator (LLM) -> validation -> solver -> templated reply.

The LLM is called once per message, only to translate. Every fact in a reply comes from the
validator, the solver or the catalog. Applying a numbered fix is deterministic (no LLM).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planner_chat.translator import TranslatorContext, translate
from planner_llm import LLMError, LLMGateway
from planner_solver.domain import StudentTerm, TermData
from planner_solver.present import render_result
from planner_solver.spec import ConstraintSpec
from planner_solver.term import TermResult, solve_term
from planner_solver.validation import ValidationContext, validate_spec

FIX_HINT = "Reply with a fix's number to apply it, or tell me what to change."


def _label(constraint: dict[str, Any]) -> str:
    if constraint.get("source_text"):
        return f"“{constraint['source_text']}”"
    return constraint["type"].replace("_", " ")


@dataclass
class ChatSession:
    context: TranslatorContext
    term: TermData
    student: StudentTerm
    validation: ValidationContext
    gateway: LLMGateway
    out_of_scope_log: Path | None = None
    spec: dict[str, Any] | None = None  # the current request, as a contract instance
    _result: TermResult | None = field(default=None, repr=False)

    def handle(self, message: str) -> str:
        text = message.strip()
        if text == "/spec":
            return self._describe()
        if text.isdigit() and self._result is not None and self._result.relaxations:
            return self._apply_fix(int(text))
        return self._translate_and_solve(text)

    # -- turns ---------------------------------------------------------------------------

    def _translate_and_solve(self, message: str) -> str:
        try:
            translation = translate(message, self.context, self.gateway, prior=self.spec)
        except LLMError as exc:
            return f"Sorry, I couldn't process that ({exc}). Your current request is unchanged."
        lines = [f"Got it: {translation.spec['restatement']}"]
        lines += [f"note: I couldn't read one part of that ({p})" for p in translation.problems]
        spec, notes = self._validated(translation.spec)
        lines += notes
        if spec is None:
            return "\n".join(lines)
        self.spec = spec
        lines.append(self._solve())
        checked = ConstraintSpec.model_validate(spec)
        lines += [
            f"question: {q.question}" + (f" [{' / '.join(q.options)}]" if q.options else "")
            for q in checked.clarifications
        ]
        for item in checked.out_of_scope:
            lines.append(f"I can't do that yet: {item.request}")
            self._log_out_of_scope(item.model_dump())
        return "\n".join(lines)

    def _apply_fix(self, number: int) -> str:
        assert self._result is not None and self.spec is not None
        fixes = self._result.relaxations
        if not 1 <= number <= len(fixes):
            return f"There's no fix {number}; pick 1–{len(fixes)}."
        dropped = fixes[number - 1].constraint_id
        constraint = next(c for c in self.spec["constraints"] if c["id"] == dropped)
        # rules that only apply to a dropped course go with it (e.g. "not with Smith for macro")
        course = (
            constraint["params"].get("course") if constraint["type"] == "include_course" else None
        )
        scoped = [
            c
            for c in self.spec["constraints"]
            if course
            and c["id"] != dropped
            and c["type"] == "instructor_preference"
            and c["params"].get("course") == course
        ]
        gone = {dropped, *(c["id"] for c in scoped)}
        self.spec["constraints"] = [c for c in self.spec["constraints"] if c["id"] not in gone]
        also = (
            f" (and {', '.join(_label(c) for c in scoped)}, which only applied to it)"
            if scoped
            else ""
        )
        return f"Dropped {_label(constraint)}{also}.\n" + self._solve()

    # -- helpers -------------------------------------------------------------------------

    def _validated(self, raw: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """Validate; a constraint with a problem is left out (and said so), the rest is kept."""
        notes: list[str] = []
        by_id = {c["id"]: c for c in raw["constraints"]}
        for _ in range(len(by_id) + 1):
            checked = validate_spec(raw, self.validation)
            notes += [f"note: {n}" for n in checked.notes if not n.startswith("default_credits")]
            if checked.ok and checked.spec is not None:
                return checked.spec.model_dump(mode="json", exclude_none=True), notes
            contradictions = [e for e in checked.errors if e.rule == 6]
            if contradictions:
                notes += [
                    f"These can't both hold: {e.message}. Tell me which to change."
                    for e in contradictions
                ]
                return None, notes
            droppable = {e.constraint_id for e in checked.errors if e.constraint_id in by_id}
            if not droppable:
                notes += [
                    f"Sorry, I couldn't use that request: {e.message}" for e in checked.errors
                ]
                return None, notes
            for error in checked.errors:
                if error.constraint_id in droppable:
                    notes.append(f"Left out {_label(by_id[error.constraint_id])}: {error.message}")
            raw = {
                **raw,
                "constraints": [c for c in raw["constraints"] if c["id"] not in droppable],
            }
            notes = list(dict.fromkeys(notes))
        return None, notes

    def _solve(self) -> str:
        assert self.spec is not None
        spec = ConstraintSpec.model_validate(self.spec)
        self._result = solve_term(spec, self.term, self.student)
        text = render_result(self._result, spec, self.term, self.student)
        return text + ("\n" + FIX_HINT if self._result.status == "infeasible" else "")

    def _describe(self) -> str:
        if not self.spec or not self.spec["constraints"]:
            return "No requests yet."
        lines = ["Your current requests:"]
        for c in self.spec["constraints"]:
            params = ", ".join(f"{k} {v}" for k, v in c["params"].items())
            lines.append(
                f"  {_label(c)} — {c['type']} ({params}) · {c['enforcement']}, weight {c['weight']}"
            )
        return "\n".join(lines)

    def _log_out_of_scope(self, item: dict[str, Any]) -> None:
        if self.out_of_scope_log is None:
            return
        self.out_of_scope_log.parent.mkdir(parents=True, exist_ok=True)
        with self.out_of_scope_log.open("a") as log:
            log.write(json.dumps(item) + "\n")
