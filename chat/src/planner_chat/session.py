"""One chat conversation: message -> translator (LLM) -> validation -> solver -> templated reply.

The LLM is called once per message, only to translate (and to say what kind of message it
is). Every fact in a reply comes from the validator, the solver, the catalog or the audit.
Applying a numbered fix is deterministic (no LLM). Questions and small talk never re-solve.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planner_chat.translator import TranslatorContext, translate
from planner_llm import LLMError, LLMGateway
from planner_solver.describe import DEFAULT_IDS, describe, summary
from planner_solver.domain import (
    Section,
    StudentTerm,
    TermData,
    blocking_reasons,
    prereq_met,
    resolve_selector,
    unknown_reasons,
    when,
)
from planner_solver.present import SHOWN, label, render_result
from planner_solver.spec import Constraint, ConstraintSpec
from planner_solver.term import Schedule, TermResult, solve_term
from planner_solver.validation import (
    DEFAULT_LOAD_NOTE,
    ValidationContext,
    canonical_course,
    validate_spec,
)

FIX_HINT = "Reply with a fix's number to apply it, or tell me what to change."
GREETING = (
    "Hi! Tell me what you want for {term}: courses, days or times to keep free, a credit "
    "load, professors to take or avoid. You can also ask what you still need to graduate."
)
THANKS = "You're welcome! Tell me if you want to change anything."
PLAN_NOT_YET = (
    "I can only plan one semester ({term}) for now; planning all the way to graduation is "
    "coming. Ask “what do I still need?” to see your open requirements."
)
NO_OPINIONS = (
    "I don't have reviews or ratings of instructors, only who teaches each section. Tell me "
    "who you'd like to take or avoid and I'll plan around it."
)
OTHER = "I can only help with your {term} schedule and what's on your audit."
CATALOG_LIMIT = 60  # rows per catalog search; `total` says how many matched


@dataclass(frozen=True)
class StudentFacts:
    """Audit facts the chat answers questions from (quoted, never generated)."""

    credits_earned: float | None = None
    credits_in_progress: float | None = None
    standing: str | None = None
    in_progress: tuple[str, ...] = ()  # course codes


# failed in-progress courses -> the student and validation context under that assumption
WhatIf = Callable[[tuple[str, ...]], tuple[StudentTerm, ValidationContext]]


def _label(constraint: dict[str, Any], term: TermData | None = None) -> str:
    return f"“{label(Constraint.model_validate(constraint), term)}”"


def _said(constraint: dict[str, Any]) -> str:
    """The student's own words for something they asked for this turn."""
    text = constraint.get("source_text")
    return f"“{text}”" if text else _label(constraint)


@dataclass
class ChatSession:
    context: TranslatorContext
    term: TermData
    student: StudentTerm
    validation: ValidationContext
    gateway: LLMGateway
    out_of_scope_log: Path | None = None
    facts: StudentFacts = StudentFacts()
    what_if: WhatIf | None = None
    spec: dict[str, Any] | None = None  # the current request, as a contract instance
    _result: TermResult | None = field(default=None, repr=False)
    _asked: set[str] = field(default_factory=set, repr=False)  # clarifications already shown
    _waived: set[str] = field(
        default_factory=set, repr=False
    )  # system defaults the student removed
    _requirement_courses: list[tuple[str, set[str]]] | None = field(default=None, repr=False)
    questions: list[dict[str, Any]] = field(default_factory=list)  # asked on the last turn
    list_schedules: bool = True  # False when the schedules are drawn elsewhere (web canvas)

    def handle(self, message: str) -> str:
        self.questions = []
        text = message.strip()
        if text == "/spec":
            return self._describe()
        if text.isdigit() and self._result is not None and self._result.relaxations:
            return self._apply_fix(int(text))
        try:
            translation = translate(text, self.context, self.gateway, prior=self._prior())
        except LLMError as exc:
            return f"Sorry, I couldn't process that ({exc}). Your current request is unchanged."
        term = self.context.target_term
        if translation.intent == "greeting":
            return GREETING.format(term=term)
        if translation.intent == "thanks":
            return THANKS
        if translation.intent == "question":
            for item in translation.spec["out_of_scope"]:
                self._log_out_of_scope(item)
            return self._answer(translation.topic, translation.courses)
        if translation.spec["mode"] == "plan":
            self._log_out_of_scope({"request": "multi-term plan", "user_text": text})
            return PLAN_NOT_YET.format(term=term)
        return self._schedule(translation.spec, translation.problems)

    # -- turns ---------------------------------------------------------------------------

    def _schedule(self, raw: dict[str, Any], problems: list[str]) -> str:
        lines = ["I couldn't read one part of that, so I left it out." for _ in problems[:1]]
        spec, notes = self._validated(raw)
        if spec is None:
            return "\n".join(lines + notes)
        spec["constraints"] = [c for c in spec["constraints"] if c["id"] not in self._waived]
        checked = ConstraintSpec.model_validate(spec)
        self.spec = {**spec, "clarifications": [], "out_of_scope": []}  # said once, not carried
        lines.insert(0, summary(checked, self.term, self.student.open_requirements))
        lines += notes
        lines.append(self._solve())
        for q in checked.clarifications:
            key = q.constraint_id or q.question
            if key not in self._asked:
                self._asked.add(key)
                options = f" [{' / '.join(q.options)}]" if q.options else ""
                lines.append(f"question: {q.question}{options}")
                self.questions.append({"question": q.question, "options": q.options or []})
        for item in checked.out_of_scope:
            lines.append(f"I can't do “{item.user_text or item.request}” yet.")
            self._log_out_of_scope(item.model_dump())
        return "\n".join(lines)

    def _apply_fix(self, number: int) -> str:
        assert self._result is not None and self.spec is not None
        fixes = self._result.relaxations
        if not 1 <= number <= len(fixes):
            return f"There's no fix {number}; pick 1–{len(fixes)}."
        return self.drop(fixes[number - 1].constraint_id)

    def drop(self, dropped: str) -> str:
        """Remove one request (a fix, or a chip the student closed) and re-solve. No LLM."""
        if self.spec is None or not any(c["id"] == dropped for c in self.spec["constraints"]):
            return "That request isn't active any more."
        self.questions = []
        if dropped in DEFAULT_IDS:
            self._waived.add(dropped)
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
            f" (and {', '.join(_label(c, self.term) for c in scoped)}, which only applied to it)"
            if scoped
            else ""
        )
        return f"Dropped {_label(constraint, self.term)}{also}.\n" + self._solve()

    def _answer(self, topic: str | None, courses: list[str]) -> str:
        term = self.context.target_term
        if topic == "remaining_requirements":
            return self._remaining()
        if topic == "credits_earned":
            return self._credits()
        if topic == "course_info":
            return self._course_info(courses)
        if topic == "what_if_fail":
            return self._what_if(courses)
        if topic == "instructor_opinion":
            return NO_OPINIONS
        return OTHER.format(term=term)

    # -- answers from the audit and the catalog -----------------------------------------------

    def _remaining(self) -> str:
        targets = self.student.open_requirements
        if not targets:
            return "Your audit shows nothing left to plan for."
        lines = ["From your audit, you still need:"]
        for target in targets.values():
            amount = ""
            if target.needed and target.unit:
                noun = target.unit if target.needed != 1 else target.unit[:-1]
                amount = f" — {target.needed:g} {noun}"
            lines.append(f"  • {target.title}{amount}")
        if self.facts.in_progress:
            lines.append(
                "This counts your in-progress courses as passed: "
                + ", ".join(self.facts.in_progress)
                + "."
            )
        return "\n".join(lines)

    def _credits(self) -> str:
        f = self.facts
        if f.credits_earned is None:
            return "Your audit doesn't show a credit total."
        text = f"Your audit shows {f.credits_earned:g} credits earned"
        if f.credits_in_progress:
            text += f", plus {f.credits_in_progress:g} in progress"
        return text + (f". Class standing: {f.standing}." if f.standing else ".")

    def _course_info(self, courses: list[str]) -> str:
        if not courses:
            return "Which course? Give me its name or code."
        lines: list[str] = []
        for text in courses:
            code = canonical_course(text)
            course = self.term.courses.get(code or "")
            if course is None:
                lines.append(f"I couldn't find {text} in the {self.context.target_term} catalog.")
                continue
            lines.append(f"{code} {course.title} ({course.credits:g} cr):")
            sections = [s for s in self.term.sections if s.course == code]
            lines += [
                f"  {s.section_id}  {when(s)}  · {', '.join(s.instructors) or 'instructor TBA'}"
                for s in sections
            ] or ["  no sections this term"]
            counts = self._counts_toward(code)
            if code in self.student.unplannable_courses:
                lines.append("  You've already taken it or are registered.")
            elif prereq_met(course.prereq, self.student) == "no":
                why = "; ".join(blocking_reasons(course.prereq, self.student))
                lines.append(f"  You can't take it yet: {why}.")
            if counts:
                lines.append(f"  Counts toward: {'; '.join(counts)}")
        return "\n".join(lines)

    def _what_if(self, courses: list[str]) -> str:
        codes = tuple(c for c in (canonical_course(x) for x in courses) if c)
        current = ", ".join(self.facts.in_progress) or "none"
        others = [c for c in codes if c not in self.facts.in_progress]
        if not codes or others:
            which = f"{', '.join(others)} isn't one of them. " if others else ""
            return f"I can check this for your in-progress courses: {current}. {which}".strip()
        if self.what_if is None:
            return OTHER.format(term=self.context.target_term)
        student, validation = self.what_if(codes)
        base = self.spec or {
            "spec_version": "0.1",
            "mode": "term",
            "target_term": self.context.target_term,
            "restatement": "",
            "constraints": [],
        }
        raw = {
            **base,
            "constraints": [c for c in base["constraints"] if c["id"] not in DEFAULT_IDS],
        }
        checked = validate_spec(raw, validation)
        if not checked.ok or checked.spec is None:
            return "Your current requests don't work under that assumption: " + "; ".join(
                e.message for e in checked.errors
            )
        result = solve_term(checked.spec, self.term, student)
        failed = " and ".join(codes)
        intro = (
            f"If you don't pass {failed}, here's {self.context.target_term} with the same "
            f"requests (I'm still planning as if you pass):"
        )
        return intro + "\n" + render_result(result, checked.spec, self.term, student)

    def catalog(self, query: str = "") -> dict[str, Any]:
        """This term's courses matching every word of `query` (code, title or instructor),
        straight from the term data. No query: the courses that count toward an open
        requirement. No LLM; nothing here is generated."""
        words = query.lower().split()
        offered: dict[str, list[Section]] = {}
        for s in self.term.sections:
            offered.setdefault(s.course, []).append(s)
        matches: list[dict[str, Any]] = []
        for code, course in sorted(self.term.courses.items()):
            sections = offered.get(code, [])
            counts = self._counts_toward(code)
            if words:
                names = " ".join(i for s in sections for i in s.instructors)
                haystack = f"{code} {code.replace(' ', '')} {course.title} {names}".lower()
                if not all(w in haystack for w in words):
                    continue
            elif not counts:
                continue
            if code in self.student.unplannable_courses:
                status, notes = "taken", []
            elif blocked := blocking_reasons(course.prereq, self.student):
                status, notes = "blocked", blocked
            elif unsure := unknown_reasons(course.prereq, self.student):
                status, notes = "check", unsure
            else:
                status, notes = "open", []
            matches.append(
                {
                    "code": code,
                    "title": course.title,
                    "credits": course.credits,
                    "status": status,
                    "notes": notes,
                    "counts_toward": counts,
                    "sections": [
                        {
                            "id": s.section_id,
                            "component": s.component,
                            "when": when(s),
                            "instructors": list(s.instructors),
                            "online": s.modality == "online",
                            "seats_open": s.seats_open,
                        }
                        for s in sections
                    ],
                }
            )
        return {"courses": matches[:CATALOG_LIMIT], "total": len(matches)}

    # -- helpers -------------------------------------------------------------------------

    def _counts_toward(self, code: str) -> list[str]:
        """Titles of the open requirements this course could count toward."""
        if self._requirement_courses is None:  # resolved once: the catalog asks per course
            self._requirement_courses = [
                (
                    t.title,
                    {
                        c
                        for sel in t.selectors
                        for c in resolve_selector(sel, self.term.courses) or set()
                    }
                    - set(t.excluded),
                )
                for t in self.student.open_requirements.values()
            ]
        return [title for title, codes in self._requirement_courses if code in codes]

    def _prior(self) -> dict[str, Any] | None:
        """The current spec for the translator, without the system's own defaults."""
        if self.spec is None:
            return None
        kept = [c for c in self.spec["constraints"] if c["id"] not in DEFAULT_IDS]
        return {**self.spec, "constraints": kept}

    def _validated(self, raw: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """Validate; a constraint with a problem is left out (and said so), the rest is kept."""
        notes: list[str] = []
        by_id = {c["id"]: c for c in raw["constraints"]}
        default_note = DEFAULT_LOAD_NOTE.split("(")[0]
        for _ in range(len(by_id) + 1):
            checked = validate_spec(raw, self.validation)
            notes += [f"note: {n}" for n in checked.notes if not n.startswith(default_note)]
            if checked.ok and checked.spec is not None:
                return checked.spec.model_dump(mode="json", exclude_none=True), list(
                    dict.fromkeys(notes)
                )
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
                    said = _said(by_id[error.constraint_id])
                    why = "I couldn't turn it into a rule" if error.rule == 5 else error.message
                    notes.append(f"Left out {said}: {why}.")
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
        text = render_result(
            self._result, spec, self.term, self.student, listing=self.list_schedules
        )
        return text + ("\n" + FIX_HINT if self._result.status == "infeasible" else "")

    def _describe(self) -> str:
        if not self.spec or not self.spec["constraints"]:
            return "No requests yet."
        lines = ["Your current requests:"]
        for c in self.spec["constraints"]:
            con = Constraint.model_validate(c)
            how = "must" if con.enforcement == "hard" else f"preference, weight {con.weight}"
            said = f"  ← “{con.source_text}”" if con.source_text else ""
            lines.append(
                f"  {describe(con, self.term, self.student.open_requirements)} · {how}{said}"
            )
        return "\n".join(lines)

    def _log_out_of_scope(self, item: dict[str, Any]) -> None:
        if self.out_of_scope_log is None:
            return
        self.out_of_scope_log.parent.mkdir(parents=True, exist_ok=True)
        with self.out_of_scope_log.open("a", encoding="utf-8") as log:
            log.write(json.dumps(item) + "\n")

    # -- structured view (the web canvas; same facts as the text) -----------------------------

    def welcome(self) -> str:
        """First message after an upload: what was read, from the audit (no LLM)."""
        f, left = self.facts, len(self.student.open_requirements)
        read = "I read your audit"
        if f.credits_earned is not None:
            read += f": {f.credits_earned:g} credits earned"
            if f.credits_in_progress:
                read += f" plus {f.credits_in_progress:g} in progress"
        read += f", {left} requirement{'s' if left != 1 else ''} still open."
        return read + " " + GREETING.format(term=self.context.target_term)

    def view(self) -> dict[str, Any]:
        targets = self.student.open_requirements
        spec = ConstraintSpec.model_validate(self.spec) if self.spec else None
        rules = [
            {
                "id": c.id,
                "text": describe(c, self.term, targets),
                "must": c.enforcement == "hard",
                "said": c.source_text or "",
                "default": c.id in DEFAULT_IDS,
            }
            for c in (spec.constraints if spec else [])
        ]
        result = self._result
        by_id = {c.id: c for c in spec.constraints} if spec else {}
        return {
            "term": self.context.target_term,
            "rules": rules,
            "status": result.status if result else None,
            "schedules": [self._schedule_view(s) for s in result.schedules[:SHOWN]]
            if result
            else [],
            "conflict_ids": list(result.conflict) if result else [],
            "conflict": [describe(by_id[c], self.term, targets) for c in result.conflict]
            if result and spec
            else [],
            "why": [fact for c in result.conflict for fact in result.reasons.get(c, [])]
            if result
            else [],
            "fixes": [
                {
                    "number": n,
                    "text": describe(by_id[r.constraint_id], self.term, targets),
                    "unlocks": r.schedules_unlocked,
                }
                for n, r in enumerate(result.relaxations if result else [], start=1)
            ],
            "questions": self.questions,
            "requirements": [
                {"title": t.title, "needed": t.needed, "unit": t.unit} for t in targets.values()
            ],
            "facts": {
                "credits_earned": self.facts.credits_earned,
                "credits_in_progress": self.facts.credits_in_progress,
                "standing": self.facts.standing,
                "in_progress": list(self.facts.in_progress),
            },
        }

    def _schedule_view(self, schedule: Schedule) -> dict[str, Any]:
        assert self._result is not None
        targets = self.student.open_requirements
        sections = {s.section_id: s for s in self.term.sections}
        rows = []
        for sid in schedule.sections:
            s = sections[sid]
            course = self.term.courses[s.course]
            rows.append(
                {
                    "id": sid,
                    "course": s.course,
                    "title": course.title,
                    "credits": course.credits,
                    "instructors": list(s.instructors),
                    "when": when(s),
                    "online": s.modality == "online",
                    "meetings": [
                        {"days": "".join(m.days), "start": m.start, "end": m.end}
                        for m in s.meetings
                    ],
                    "counts_toward": [
                        targets[r].title
                        for r in targets
                        if s.course in schedule.contributions.get(r, [])
                    ],
                    "warnings": self._result.prereq_unchecked.get(s.course, []),
                }
            )
        progress = []
        for rid, target in targets.items():
            codes = schedule.contributions.get(rid, [])
            credits = sum(self.term.courses[c].credits for c in codes)
            progress.append(
                {
                    "title": target.title,
                    "needed": target.needed,
                    "unit": target.unit,
                    "planned": credits if target.unit == "credits" else len(codes),
                    "courses": codes,
                }
            )
        return {
            "credits": schedule.credits,
            "sections": rows,
            "missed_rules": schedule.soft_missed,  # "if possible" requests this plan can't meet
            "progress": progress,  # what this plan adds to each open requirement
        }
