"""One chat conversation: message -> translator (LLM) -> validation -> solver -> templated reply.

The LLM is called once per message, only to translate (and to say what kind of message it
is). Every fact in a reply comes from the validator, the solver, the catalog or the audit.
Applying a numbered fix, picking an option and undoing are deterministic (no LLM). Questions
and small talk never re-solve. Each turn can offer follow-ups the student taps (suggestions).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from planner_chat.answers import (
    Advisor,
    Answer,
    Plan,
    Suggestion,
    requirement_hint,
    term_name,
)
from planner_chat.phrasing import Phraser
from planner_chat.translator import Translation, TranslatorContext, translate
from planner_llm import LLMError, LLMGateway
from planner_solver.describe import DEFAULT_IDS, describe, summary
from planner_solver.domain import (
    Section,
    StudentTerm,
    TermData,
    blocking_reasons,
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
OTHER = (
    "I can help with your {term} schedule and with what's on your audit: what you still need, "
    "what a course counts toward, what you can take."
)
UNDO = Suggestion("Undo", "/undo")
HISTORY = 12  # messages kept for the translator (it reads the last few)
LOAD_STAYS = (
    "Your credit load can't be removed, only changed: tell me the load you want, "
    "like “12–15 credits”."
)
PLAN_NAMES = "ABCDEFGHIJ"
CATALOG_LIMIT = 60  # rows per catalog search; `total` says how many matched


@dataclass(frozen=True)
class StudentFacts:
    """Audit facts the chat answers questions from (quoted, never generated)."""

    credits_earned: float | None = None
    credits_in_progress: float | None = None
    standing: str | None = None
    in_progress: tuple[str, ...] = ()  # course codes


@dataclass(frozen=True)
class Choice:
    """One way to fit a newly asked-for course: into the plan on screen, or a rebuild."""

    text: str
    spec: dict[str, Any]  # the request once chosen (it includes the new course)
    result: TermResult | None  # the edited plan; None: solve from scratch


# failed in-progress courses -> the student and validation context under that assumption
WhatIf = Callable[[tuple[str, ...]], tuple[StudentTerm, ValidationContext]]


def _label(constraint: dict[str, Any], term: TermData | None = None) -> str:
    return f"“{label(Constraint.model_validate(constraint), term)}”"


def _key(c: dict[str, Any]) -> tuple[str, str, str]:
    """A constraint's meaning, without its id or wording."""
    return (c["type"], json.dumps(c["params"], sort_keys=True), c["enforcement"])


def _asked_courses(spec: dict[str, Any]) -> set[str]:
    return {c["params"]["course"] for c in spec["constraints"] if c["type"] == "include_course"}


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
    _advisor: Advisor | None = field(default=None, repr=False)
    _noted: set[str] = field(default_factory=set, repr=False)  # notes already shown
    _undo: tuple[dict[str, Any] | None, TermResult | None, set[str]] | None = field(
        default=None, repr=False
    )
    history: list[tuple[str, str]] = field(default_factory=list)  # ("student"|"planner", text)
    suggestions: list[Suggestion] = field(default_factory=list)  # follow-ups for this turn
    phraser: Phraser | None = None  # natural wording of each reply, checked against the draft
    questions: list[dict[str, Any]] = field(default_factory=list)  # asked on the last turn
    list_schedules: bool = True  # False when the schedules are drawn elsewhere (web canvas)
    plan: int = 0  # the schedule the student is looking at (edits apply to it)
    choices: list[Choice] = field(default_factory=list)  # offered on the last turn

    @property
    def advisor(self) -> Advisor:
        if self._advisor is None:
            self._advisor = Advisor(
                self.term, self.student, self.facts.in_progress, self.context.target_term
            )
        return self._advisor

    @property
    def term_label(self) -> str:
        return term_name(self.context.target_term)

    def handle(self, message: str, plan: int = 0) -> str:
        """One student message -> the reply (also kept in `history` for the next turn)."""
        earlier = list(self.history)
        self.suggestions = []
        reply = self._respond(message.strip(), plan, earlier)
        if self.phraser is not None and not message.strip().startswith("/"):
            reply = self.phraser.reword(reply, message.strip())
        self.history = [*earlier, ("student", message.strip()), ("planner", reply)][-HISTORY:]
        return reply

    def _respond(self, text: str, plan: int, earlier: list[tuple[str, str]]) -> str:
        self.questions = []
        self.plan = plan
        if text == "/spec":
            return self._describe()
        if text == "/undo":
            return self._restore()
        if text.isdigit() and self.choices:
            return self._apply_choice(int(text))
        self.choices = []
        if text.isdigit() and self._result is not None and self._result.relaxations:
            return self._apply_fix(int(text))
        try:
            translation = translate(
                text,
                self.context,
                self.gateway,
                prior=self._prior(),
                history=earlier,
                plans=self._plan_lines(),
            )
        except LLMError as exc:
            return f"Sorry, I couldn't process that ({exc}). Your current request is unchanged."
        term = self.term_label
        if translation.intent == "greeting":
            self.suggestions = self._starters()
            return GREETING.format(term=term)
        if translation.intent == "thanks":
            return THANKS
        if translation.intent == "question":
            for item in translation.spec["out_of_scope"]:
                self._log_out_of_scope(item)
            return self._answer(translation)
        if translation.spec["mode"] == "plan":
            self._log_out_of_scope({"request": "multi-term plan", "user_text": text})
            self.suggestions = [Suggestion("What do I still need?", "What do I still need?")]
            return PLAN_NOT_YET.format(term=term)
        return self._schedule(translation.spec, translation.problems)

    def _starters(self) -> list[Suggestion]:
        return [
            Suggestion("What do I still need?", "What do I still need?"),
            Suggestion("Plan next semester", "Plan my next semester"),
        ]

    # -- turns ---------------------------------------------------------------------------

    def _schedule(self, raw: dict[str, Any], problems: list[str]) -> str:
        lines = ["I couldn't read one part of that, so I left it out." for _ in problems[:1]]
        spec, notes = self._validated(raw)
        if spec is None:
            return "\n".join(lines + notes)
        spec["constraints"] = [c for c in spec["constraints"] if c["id"] not in self._waived]
        checked = ConstraintSpec.model_validate(spec)
        spec = {**spec, "clarifications": [], "out_of_scope": []}  # said once, not carried
        if self.list_schedules:
            lines.insert(0, summary(checked, self.term, self.student.open_requirements))
        else:  # the web shows every request as a chip: say only what changed
            lines.insert(0, self._changes(spec))
        lines += notes
        added = self._added_courses(spec)
        if added:  # only new courses: offer to fit them into the plan on screen
            lines.append(self._offer_edits(spec, added))
        else:
            self._remember()
            self.spec = spec
            lines.append(self._solve())
            self.suggestions = [UNDO]
        for q in checked.clarifications:
            key = q.constraint_id or q.question
            if key not in self._asked:
                self._asked.add(key)
                options = f" [{' / '.join(q.options)}]" if q.options else ""
                lines.append(
                    f"question: {q.question}{options}" if self.list_schedules else q.question
                )
                self.questions.append({"question": q.question, "options": q.options or []})
        for item in checked.out_of_scope:
            lines.append(f"I can't do “{item.user_text or item.request}” yet.")
            self._log_out_of_scope(item.model_dump())
        return "\n".join(lines)

    def _changes(self, spec: dict[str, Any]) -> str:
        """What this turn changed, in the student's terms (plus the load assumption, once)."""
        targets = self.student.open_requirements

        def keyed(constraints: list[dict[str, Any]]) -> dict[tuple[str, str, str], Any]:
            return {_key(c): c for c in constraints if c["id"] not in DEFAULT_IDS}

        before = keyed(self.spec["constraints"] if self.spec else [])
        after = keyed(spec["constraints"])

        def said(c: dict[str, Any]) -> str:
            return f"“{describe(Constraint.model_validate(c), self.term, targets)}”"

        parts = []
        if added := [said(c) for k, c in after.items() if k not in before]:
            many = f"{len(added)} requests (listed above the calendar)"
            parts.append("added " + (many if len(added) > 3 else ", ".join(added)))
        if removed := [said(c) for k, c in before.items() if k not in after]:
            parts.append("dropped " + ", ".join(removed))
        text = f"Got it: {'; '.join(parts)}." if parts else "Your requests are the same."
        load = next((c for c in spec["constraints"] if c["id"] == "default_credits"), None)
        if load and "load" not in self._noted:
            self._noted.add("load")
            low, high = load["params"]["min"], load["params"]["max"]
            text += (
                f" I'm planning a full-time load ({low:g}–{high:g} credits); tell me if you "
                "want a different one."
            )
        return text

    def _remember(self) -> None:
        """Keep the state before a change, so "Undo" can bring it back."""
        spec = json.loads(json.dumps(self.spec)) if self.spec is not None else None
        self._undo = (spec, self._result, set(self._waived))

    def _restore(self) -> str:
        if self._undo is None:
            return "There's nothing to undo."
        self.spec, self._result, self._waived = self._undo
        self._undo = None
        self.choices = []
        return "Undone: your requests and plans are back to how they were."

    def _apply_fix(self, number: int) -> str:
        assert self._result is not None and self.spec is not None
        fixes = self._result.relaxations
        if not 1 <= number <= len(fixes):
            return f"There's no fix {number}; pick 1–{len(fixes)}."
        return self.drop(fixes[number - 1].constraint_id)

    def _offer_edits(self, spec: dict[str, Any], added: list[str]) -> str:
        """New courses for a plan the student already has: add them to it, swap one class
        out, or rebuild. Every option keeps their requests; nothing changes until they pick."""
        assert self._result is not None
        index = min(self.plan, len(self._result.schedules) - 1)
        plan = self._result.schedules[index]
        name = f"Plan {PLAN_NAMES[index]}"
        new = [c for c in added if c not in plan.courses]
        if not new:
            kept = self._fit(spec, plan.sections, [])
            self.spec = spec
            self._result = kept or self._result
            return f"{' and '.join(added)} is already in {name}, so I kept it as it is."
        what = " and ".join(f"{c} ({self.term.courses[c].title})" for c in new)
        by_id = {s.section_id: s for s in self.term.sections}
        asked = _asked_courses(spec)
        options: list[tuple[str, TermResult | None]] = [
            (f"Add {what} to {name}", self._fit(spec, plan.sections, new))
        ]
        for course in plan.courses:
            if course not in asked:  # never swap out a course they asked for
                keep = [s for s in plan.sections if by_id[s].course != course]
                title = self.term.courses[course].title
                options.append((f"Swap out {course} ({title})", self._fit(spec, keep, new)))
        self.choices = [
            Choice(
                f"{text} → {fit.schedules[0].credits:g} credits"
                + self._tradeoffs(spec, plan, fit.schedules[0]),
                spec,
                fit,
            )
            for text, fit in options
            if fit is not None
        ]
        if not self.choices:
            self.spec = spec
            return (
                f"{what} doesn't fit into {name} with your requests, so I rebuilt the plans "
                "around it.\n" + self._solve()
            )
        self.choices.append(Choice("Rebuild every plan around it", spec, None))
        if not self.list_schedules:  # the web shows the options as buttons
            return f"Where should {what} go? Pick one of the options below."
        listing = "\n".join(f"{n}. {c.text}" for n, c in enumerate(self.choices, start=1))
        return f"Where should {what} go?\n{listing}\nReply with a number."

    def _fit(self, spec: dict[str, Any], keep: list[str], new: list[str]) -> TermResult | None:
        """The plan made of exactly the `keep` sections plus the `new` courses, under every
        request; None if it can't hold."""
        keep_ids = set(keep)
        kept = {s.course for s in self.term.sections if s.section_id in keep_ids}
        allowed = tuple(
            s for s in self.term.sections if s.section_id in keep_ids or s.course in new
        )
        pins = [
            {
                "id": f"keep_{n}",
                "type": "include_course",
                "params": {"course": course},
                "enforcement": "hard",
                "weight": 5,
                "weight_source": "default",
                "confidence": 1.0,
                "source_text": "",
            }
            for n, course in enumerate(sorted(kept - _asked_courses(spec)))
        ]
        pinned = ConstraintSpec.model_validate(
            {**spec, "constraints": [*spec["constraints"], *pins]}
        )
        data = self.term.model_copy(update={"sections": allowed})
        result = solve_term(pinned, data, self.student, limit=1)
        if result.status != "ok" or not result.schedules:
            return None
        return replace(result, missed=[])  # bottlenecks of a pinned plan would mislead

    def _tradeoffs(self, spec: dict[str, Any], before: Schedule, after: Schedule) -> str:
        """What an option gives up: preferences it misses, requirements it stops helping."""
        by_id = {c["id"]: c for c in spec["constraints"]}
        missed = [_label(by_id[c], self.term) for c in after.soft_missed if c in by_id]
        targets = self.student.open_requirements
        lost = [
            targets[r].title.split(" › ")[-1]
            for r in before.contributions
            if r not in after.contributions and r in targets
        ]
        text = f" (misses {', '.join(missed)})" if missed else ""
        return text + (f" · loses progress on {', '.join(lost)}" if lost else "")

    def _apply_choice(self, number: int) -> str:
        if not 1 <= number <= len(self.choices):
            return f"There's no option {number}; pick 1–{len(self.choices)}."
        choice = self.choices[number - 1]
        self.choices = []
        self._remember()
        self.suggestions = [UNDO]
        self.spec = choice.spec
        if choice.result is None:
            return self._solve()
        self._result = choice.result
        spec = ConstraintSpec.model_validate(self.spec)
        shown = render_result(
            self._result, spec, self.term, self.student, listing=self.list_schedules
        )
        return f"Done: {choice.text.split(' → ')[0]}.\n{shown}"

    def _added_courses(self, spec: dict[str, Any]) -> list[str]:
        """The courses a new request adds, when adding them is all it does and a plan exists."""
        result = self._result
        if self.spec is None or result is None or result.status != "ok" or not result.schedules:
            return []

        before = {_key(c) for c in self.spec["constraints"] if c["id"] not in DEFAULT_IDS}
        after = {_key(c): c for c in spec["constraints"] if c["id"] not in DEFAULT_IDS}
        extra = [c for k, c in after.items() if k not in before]
        if not extra or not before <= after.keys():
            return []
        if any(c["type"] != "include_course" or c["enforcement"] != "hard" for c in extra):
            return []
        return [c["params"]["course"] for c in extra]

    def drop(self, dropped: str) -> str:
        """Remove one request (a fix, or a chip the student closed) and re-solve. No LLM."""
        if self.spec is None or not any(c["id"] == dropped for c in self.spec["constraints"]):
            return "That request isn't active any more."
        if dropped == "default_credits":  # the full-time band is the only cap on the load
            return LOAD_STAYS
        self.questions = []
        self.choices = []
        self._remember()
        self.suggestions = [UNDO]
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
        # re-validate what's left, so the full-time band returns when their own load goes
        rest = [c for c in self.spec["constraints"] if c["id"] not in gone | DEFAULT_IDS]
        respec, _ = self._validated({**self.spec, "constraints": rest})
        if respec is None:
            self.spec["constraints"] = [c for c in self.spec["constraints"] if c["id"] not in gone]
        else:
            kept = [c for c in respec["constraints"] if c["id"] not in self._waived]
            self.spec = {**respec, "constraints": kept, "clarifications": [], "out_of_scope": []}
        also = (
            f" (and {', '.join(_label(c, self.term) for c in scoped)}, which only applied to it)"
            if scoped
            else ""
        )
        return f"Dropped {_label(constraint, self.term)}{also}.\n" + self._solve()

    def _answer(self, asked: Translation) -> str:
        topic, a = asked.topic, self.advisor
        answer: Answer
        if topic == "remaining_requirements":
            answer = a.remaining()
        elif topic == "requirement_details":
            answer = a.requirement_details(asked.requirements)
        elif topic == "course_info":
            answer = a.course_info(asked.courses)
        elif topic == "course_options":
            answer = a.course_options(asked.subjects, asked.courses, asked.requirements)
        elif topic == "plan_progress":
            answer = a.plan_progress(
                self._plans(asked.plans),
                self.facts.credits_earned,
                self.facts.credits_in_progress,
            )
        elif topic == "credits_earned":
            answer = Answer(self._credits())
        elif topic == "what_if_fail":
            answer = Answer(self._what_if(asked.courses))
        elif topic == "instructor_opinion":
            answer = Answer(NO_OPINIONS)
        else:
            answer = Answer(OTHER.format(term=self.term_label), self._starters())
        self.suggestions = answer.suggestions
        return answer.text

    # -- answers from the audit and the catalog -----------------------------------------------

    def _shown_plans(self) -> list[Plan]:
        schedules = self._result.schedules[:SHOWN] if self._result else []
        return [
            Plan(f"Plan {PLAN_NAMES[i]}", s.credits, s.courses, s.contributions)
            for i, s in enumerate(schedules)
        ]

    def _plans(self, letters: list[str]) -> list[Plan]:
        """The plans a question is about: the letters named, else the one on screen."""
        shown = self._shown_plans()
        picked = [p for p in shown if p.name[-1] in {x.strip().upper()[-1:] for x in letters}]
        if picked:
            return picked
        return shown[min(self.plan, len(shown) - 1) : min(self.plan, len(shown) - 1) + 1]

    def _plan_lines(self) -> list[str]:
        """What the translator sees of the plans, to resolve "plan A" / "this plan"."""
        index = min(self.plan, len(self._shown_plans()) - 1)
        return [
            f"{p.name}: {p.credits:g} credits, {', '.join(p.courses)}"
            + (" (on screen)" if i == index else "")
            for i, p in enumerate(self._shown_plans())
        ]

    def _credits(self) -> str:
        f = self.facts
        if f.credits_earned is None:
            return "Your audit doesn't show a credit total."
        text = f"Your audit shows {f.credits_earned:g} credits earned"
        if f.credits_in_progress:
            text += f", plus {f.credits_in_progress:g} in progress"
        return text + (f". Class standing: {f.standing}." if f.standing else ".")

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
        return self.advisor.counts_toward(code)

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
        fresh = [w for w in self._result.warnings if w not in self._noted]
        self._noted |= set(fresh)  # a note is said once per conversation, not every turn
        shown = replace(self._result, warnings=fresh)
        text = render_result(shown, spec, self.term, self.student, listing=self.list_schedules)
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
        self.suggestions = self._starters()
        return read + " " + GREETING.format(term=self.term_label)

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
                "removable": c.id != "default_credits",
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
            "choices": [{"number": n, "text": c.text} for n, c in enumerate(self.choices, 1)],
            "requirements": [
                {
                    "title": t.title,
                    "needed": t.needed,
                    "unit": t.unit,
                    "hint": requirement_hint(self.advisor, rid, t),  # "ECON 1400 · 3 cr"
                }
                for rid, t in targets.items()
            ],
            "suggestions": [{"label": x.label, "message": x.message} for x in self.suggestions],
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
        amounts = self.advisor.progress(schedule.contributions)
        progress = [
            {
                "title": target.title,
                "needed": target.needed,
                "unit": target.unit,
                "planned": amounts[rid][0],
                "courses": schedule.contributions.get(rid, []),
            }
            for rid, target in targets.items()
        ]
        return {
            "credits": schedule.credits,
            "sections": rows,
            "missed_rules": schedule.soft_missed,  # "if possible" requests this plan can't meet
            "progress": progress,  # what this plan adds to each open requirement
        }
