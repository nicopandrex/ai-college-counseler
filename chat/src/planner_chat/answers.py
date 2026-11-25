"""Answers to degree questions, from the audit and the term's catalog only (no LLM).

Each answer is short, leads with what was asked, and offers a few follow-ups the student can
tap. Every course, credit amount, time and requirement in the text comes from the data.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from planner_solver.domain import (
    AllPrereq,
    AnyPrereq,
    Course,
    CoursePrereq,
    Prereq,
    RequirementTarget,
    Section,
    StudentTerm,
    TermData,
    blocking_reasons,
    prereq_met,
    resolve_selector,
    unknown_reasons,
    when,
)
from planner_solver.validation import canonical_course

SHOWN = 6  # list items before "and N more"
SEASONS = {"SP": "Spring", "SU": "Summer", "FA": "Fall", "WI": "Winter"}


@dataclass(frozen=True)
class Suggestion:
    label: str  # what the chip says
    message: str  # what tapping it sends


@dataclass
class Answer:
    text: str
    suggestions: list[Suggestion] = field(default_factory=list)


def term_name(term: str) -> str:
    """ "2027SP" -> "Spring 2027"; anything else as given."""
    m = re.fullmatch(r"(\d{4})(SP|SU|FA|WI)", term)
    return f"{SEASONS[m.group(2)]} {m.group(1)}" if m else term


def short(title: str) -> str:
    """A requirement's own name: no block path, no "N courses from the following" text.
    "ELECTIVES › OPEN LEVEL. 1 additional course/3 credits…" -> "Open Level"."""
    name = title.split(" › ")[-1]
    head, dot, _ = name.partition(". ")
    if dot and head.isupper() and len(head) > 2:
        return head.title().replace("&", "and")
    return name


def plural(n: float, noun: str) -> str:
    return f"{n:g} {noun}{'' if n == 1 else 's'}"


def listing(items: list[str], limit: int = SHOWN) -> str:
    """ "a, b and c", or "a, b, c and 4 more"."""
    shown, rest = items[:limit], len(items) - limit
    if rest > 0:
        return f"{', '.join(shown)} and {rest} more"
    return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


def why_not(prereq: Prereq | None, student: StudentTerm) -> str:
    """Blocking reasons as one phrase: "requires ECON 1400 and ECON 1450; ..."."""
    reasons = blocking_reasons(prereq, student)
    courses = [r.removeprefix("requires ") for r in reasons if _REQUIRES.fullmatch(r)]
    rest = [r for r in reasons if not _REQUIRES.fullmatch(r)]
    return "; ".join(([f"requires {listing(courses)}"] if courses else []) + rest)


_REQUIRES = re.compile(r"requires [A-Z]{2,5} \d{4}[A-Z]?")


def _course_codes(prereq: Prereq | None, concurrent_only: bool = False) -> set[str]:
    if prereq is None:
        return set()
    if isinstance(prereq, CoursePrereq):
        return {prereq.code} if prereq.concurrent_ok or not concurrent_only else set()
    if isinstance(prereq, AllPrereq | AnyPrereq):
        return set().union(*(_course_codes(p, concurrent_only) for p in prereq.items))
    return set()


@dataclass
class Advisor:
    term: TermData
    student: StudentTerm
    in_progress: tuple[str, ...] = ()
    term_code: str = ""  # the term being planned ("2027SP"); default: the data's own code
    _req_courses: dict[str, set[str]] | None = field(default=None, repr=False)
    _sections: dict[str, list[Section]] | None = field(default=None, repr=False)

    # -- lookups -----------------------------------------------------------------------------

    @property
    def term_label(self) -> str:
        return term_name(self.term_code or self.term.term)

    def requirement_courses(self) -> dict[str, set[str]]:
        """Requirement id -> every catalog course that counts toward it."""
        if self._req_courses is None:
            self._req_courses = {
                rid: {
                    c
                    for sel in t.selectors
                    for c in resolve_selector(sel, self.term.courses) or set()
                }
                - set(t.excluded)
                for rid, t in self.student.open_requirements.items()
            }
        return self._req_courses

    def sections(self, code: str) -> list[Section]:
        if self._sections is None:
            self._sections = {}
            for s in self.term.sections:
                self._sections.setdefault(s.course, []).append(s)
        return self._sections.get(code, [])

    def counts_toward(self, code: str) -> list[str]:
        targets = self.student.open_requirements
        return [
            targets[r].title for r, codes in self.requirement_courses().items() if code in codes
        ]

    def named(self, code: str) -> str:
        course = self.term.courses.get(code)
        return f"{code} {course.title}" if course else code

    def credits_each(self, codes: set[str]) -> tuple[float, float] | None:
        found = sorted({self.term.courses[c].credits for c in codes if c in self.term.courses})
        return (found[0], found[-1]) if found else None

    def amount(self, rid: str) -> str:
        """How much a requirement still needs, with credits worked out from the catalog."""
        target = self.student.open_requirements[rid]
        codes = self.requirement_courses().get(rid, set())
        each = self.credits_each(codes)
        single = len(codes) == 1 and (target.needed in (None, 1)) and target.unit != "credits"
        if single:  # one course does it: name it
            code = next(iter(codes))
            return f"{code} ({plural(each[0], 'credit')})" if each else code
        if target.needed is None or target.unit is None:
            return ""
        n = target.needed
        if target.unit == "credits":
            if each and each[0] == each[1] and each[0] > 0:
                return f"{plural(n, 'credit')} (about {plural(math.ceil(n / each[0]), 'course')})"
            return plural(n, "credit")
        if each and each[0] == each[1]:
            return f"{plural(n, 'course')} ({n * each[0]:g} credits)"
        if each:
            return f"{plural(n, 'course')} ({each[0]:g}–{each[1]:g} credits each)"
        return plural(n, "course")

    def total_credits(self, rids: list[str]) -> float | None:
        """Credits the listed requirements add up to, when every one is known exactly."""
        total = 0.0
        for rid in rids:
            target = self.student.open_requirements[rid]
            each = self.credits_each(self.requirement_courses().get(rid, set()))
            if target.needed is None or target.unit is None:
                return None
            if target.unit == "credits":
                total += target.needed
            elif each and each[0] == each[1]:
                total += target.needed * each[0]
            else:
                return None
        return total

    def status(self, course: Course, student: StudentTerm | None = None) -> str:
        """taken / blocked / check / open."""
        student = student or self.student
        if course.code in self.student.unplannable_courses:
            return "taken"
        met = prereq_met(course.prereq, student)
        return {"no": "blocked", "unknown": "check"}.get(met, "open")

    def offered(self, codes: set[str]) -> list[Course]:
        return [
            self.term.courses[c]
            for c in sorted(codes)
            if c in self.term.courses and self.sections(c)
        ]

    def depends_on(self, code: str, base: str, seen: frozenset[str] = frozenset()) -> bool:
        """Does `code` need `base`, directly or through another course's prerequisites?"""
        course = self.term.courses.get(code)
        if course is None or code in seen:
            return False
        needs = _course_codes(course.prereq)
        return base in needs or any(self.depends_on(n, base, seen | {code}) for n in needs)

    # -- answers -----------------------------------------------------------------------------

    def remaining(self) -> Answer:
        targets = self.student.open_requirements
        if not targets:
            return Answer("Your audit shows nothing left to plan for.")
        groups: dict[str, list[str]] = {}
        for rid, target in targets.items():
            head = target.title.split(" › ")[0] if " › " in target.title else ""
            amount = self.amount(rid)
            groups.setdefault(head, []).append(
                f"  • {short(target.title)}" + (f": {amount}" if amount else "")
            )
        lines = [f"You have {plural(len(targets), 'requirement')} left:"]
        for head, items in groups.items():
            if head:
                lines.append(head)
            lines += items
        if self.in_progress:
            lines.append(
                f"(I'm counting your {plural(len(self.in_progress), 'in-progress course')} "
                "as passed.)"
            )
        with_courses = [r for r, codes in self.requirement_courses().items() if codes]
        suggestions = [
            Suggestion(
                f"What counts for {short(targets[r].title)}?",
                f"What courses count for {short(targets[r].title)}?",
            )
            for r in with_courses[:2]
        ]
        suggestions.append(Suggestion("Plan next semester", "Plan my next semester"))
        return Answer("\n".join(lines), suggestions)

    def requirement_details(self, rids: list[str]) -> Answer:
        targets = self.student.open_requirements
        rids = [r for r in rids if r in targets]
        if not rids:
            return Answer(
                "Which requirement do you mean?",
                [
                    Suggestion(short(t.title), f"What counts for {short(t.title)}?")
                    for t in list(targets.values())[:4]
                ],
            )
        lines: list[str] = []
        total = self.total_credits(rids)
        if len(rids) > 1 and total is not None:
            lines.append(f"Together those come to {plural(total, 'credit')}:")
        suggestions: list[Suggestion] = []
        for rid in rids:
            target = targets[rid]
            amount = self.amount(rid)
            lines.append(f"{short(target.title)}" + (f": {amount}." if amount else "."))
            text, open_now = self._options_for(rid)
            lines += text
            for course in open_now[:1]:
                suggestions.append(
                    Suggestion(f"Add {course.code}", f"Add {course.code} to my schedule")
                )
        return Answer("\n".join(lines), suggestions[:3])

    def _options_for(self, rid: str) -> tuple[list[str], list[Course]]:
        codes = self.requirement_courses().get(rid, set())
        if not codes:
            return ["  Your audit doesn't list which courses count for it."], []
        if len(codes) == 1 and not self.offered(codes):
            return [f"  {self.named(next(iter(codes)))} isn't offered in {self.term_label}."], []
        offered = [c for c in self.offered(codes) if self.status(c) != "taken"]
        if not offered:
            return [f"  None of the courses that count are offered in {self.term_label}."], []
        open_now = [c for c in offered if self.status(c) != "blocked"]
        blocked = [c for c in offered if self.status(c) == "blocked"]
        if len(offered) == 1:
            course = offered[0]
            if blocked:
                why = why_not(course.prereq, self.student)
                return [
                    f"  It's offered in {self.term_label}, but you can't take it yet: {why}."
                ], []
            return [f"  It's offered in {self.term_label}, and you can take it."], open_now
        lines = []
        if open_now:
            names = [f"{c.code} ({c.credits:g} cr)" for c in open_now]
            lines.append(
                f"  You can take {len(open_now)} of them in {self.term_label}: {listing(names)}."
            )
        if blocked:
            example = blocked[0]
            why = why_not(example.prereq, self.student)
            lines.append(
                f"  {plural(len(blocked), 'more course')} need prerequisites first "
                f"(e.g. {example.code}: {why})."
            )
        return lines, open_now

    def course_options(self, subjects: list[str], alongside: list[str], rids: list[str]) -> Answer:
        """Which courses the student can take, by subject or requirement; optionally while
        also taking `alongside` (which then can't count as a prerequisite yet)."""
        along = [c for c in (canonical_course(x) for x in alongside) if c in self.term.courses]
        subjects = [s.upper() for s in subjects] or sorted({c.split()[0] for c in along})
        pool: set[str] = set()
        for subject in subjects:
            pool |= {c for c in self.term.courses if c.split()[0] == subject}
        for rid in rids:
            pool |= self.requirement_courses().get(rid, set())
        if not pool:
            return Answer(
                "Which subject or requirement should I look at? For example, “what ECON "
                "classes can I take?”"
            )
        courses = [c for c in self.offered(pool - set(along)) if self.status(c) != "taken"]
        scope = " / ".join(subjects) or "matching"
        if not courses:
            return Answer(f"No {scope} courses you haven't taken are offered in {self.term_label}.")
        now = [c for c in courses if self.status(c) != "blocked"]
        later = [c for c in courses if self.status(c) == "blocked"]
        lines = [
            f"{plural(len(courses), f'{scope} course')} you haven't taken are offered in "
            f"{self.term_label}."
        ]
        if along:
            both = " and ".join(along)
            waits = [c for c in later if any(a in _course_codes(c.prereq) for a in along)]
            other = [c for c in later if c not in waits]
            together = [
                c for c in waits if set(along) <= _course_codes(c.prereq, concurrent_only=True)
            ]
            waits = [c for c in waits if c not in together]
            reach = [c for c in courses if any(self.depends_on(c.code, a) for a in along)]
            if now:
                lines.append(
                    f"Alongside {both}, you can take {len(now)}: "
                    f"{listing([self.named(c.code) for c in now])}."
                )
            if together:
                lines.append(
                    f"{len(together)} can be taken in the same term as {both}: "
                    f"{listing([c.code for c in together])}."
                )
            if waits:
                lines.append(
                    f"{len(waits)} need {both} finished first, so not this term: "
                    f"{listing([c.code for c in waits])}."
                )
            if other:
                example = other[0]
                why = why_not(example.prereq, self.student)
                lines.append(f"{len(other)} need other courses first (e.g. {example.code}: {why}).")
            if reach and len(reach) < len(courses):
                lines.insert(
                    1,
                    f"So {both} isn't a prerequisite for everything: {len(reach)} of the "
                    f"{len(courses)} need it, directly or through another course.",
                )
            elif reach:
                lines.insert(
                    1, f"Every one of them needs {both}, directly or through another course."
                )
        else:
            if now:
                lines.append(
                    f"You can take {len(now)} now: {listing([self.named(c.code) for c in now])}."
                )
            if later:
                example = later[0]
                why = why_not(example.prereq, self.student)
                lines.append(
                    f"{plural(len(later), 'more')} need prerequisites first "
                    f"(e.g. {example.code}: {why})."
                )
        unsure = [c for c in now if self.status(c) == "check"]
        if unsure:
            lines.append(
                "I couldn't fully check the prerequisites of "
                f"{listing([c.code for c in unsure], 3)}, "
                "so confirm those with the department."
            )
        suggestions = [Suggestion(f"Add {c.code}", f"Add {c.code} to my schedule") for c in now[:2]]
        if later:
            suggestions.append(
                Suggestion(f"About {later[0].code}", f"Tell me about {later[0].code}")
            )
        return Answer("\n".join(lines), suggestions)

    def course_info(self, asked: list[str]) -> Answer:
        if not asked:
            return Answer("Which course? Give me its name or code.")
        parts: list[str] = []
        suggestions: list[Suggestion] = []
        for text in asked:
            code = canonical_course(text)
            course = self.term.courses.get(code or "")
            if course is None or code is None:
                parts.append(f"I couldn't find {text} in the {self.term_label} catalog.")
                continue
            lines = [f"{code} {course.title} is {plural(course.credits, 'credit')}."]
            sections = self.sections(code)
            if not sections:
                lines.append(f"It isn't offered in {self.term_label}.")
            else:
                described = [
                    f"{s.section_id.removeprefix(code).strip() or s.section_id} {when(s)}"
                    + (f" ({', '.join(s.instructors)})" if s.instructors else "")
                    for s in sections
                ]
                lines.append(
                    f"{self.term_label} has {plural(len(sections), 'section')}: "
                    f"{listing(described, 4)}."
                )
            status = self.status(course)
            if status == "taken":
                lines.append("You've already taken it (or you're registered).")
            elif status == "blocked":
                lines.append("You can't take it yet: " f"{why_not(course.prereq, self.student)}.")
            elif status == "check":
                lines.append(
                    "Check before registering: "
                    f"{'; '.join(unknown_reasons(course.prereq, self.student))}."
                )
            elif course.prereq is None:
                lines.append("It has no prerequisites.")
            else:
                lines.append("You meet its prerequisites.")
            unlocks = [
                c.code
                for c in self.offered(set(self.term.courses))
                if code in _course_codes(c.prereq)
            ]
            if unlocks:
                lines.append(
                    f"It's a prerequisite for {plural(len(unlocks), 'course')} this term: "
                    f"{listing(unlocks, 4)}."
                )
            counts = self.counts_toward(code)
            if counts:
                lines.append(f"It counts toward {listing([short(t) for t in counts], 3)}.")
            parts.append(" ".join(lines))
            if status in ("open", "check") and sections:
                suggestions.append(Suggestion(f"Add {code}", f"Add {code} to my schedule"))
            if unlocks:
                suggestions.append(
                    Suggestion(
                        "What else can I take?",
                        f"What other {code.split()[0]} classes can I take alongside {code}?",
                    )
                )
        return Answer("\n\n".join(parts), suggestions[:3])

    # -- plans --------------------------------------------------------------------------------

    def progress(self, contributions: dict[str, list[str]]) -> dict[str, tuple[float, str]]:
        """Requirement id -> (amount a plan adds, done / partial / counts / none). The amount is
        in the requirement's unit: credits, else courses."""
        out: dict[str, tuple[float, str]] = {}
        for rid, target in self.student.open_requirements.items():
            codes = contributions.get(rid, [])
            if target.unit == "credits":
                planned = sum(self.term.courses[c].credits for c in codes if c in self.term.courses)
            else:
                planned = float(len(codes))
            if not codes:
                state = "none"
            elif target.needed is None:
                state = "counts"
            else:
                state = "done" if planned >= target.needed else "partial"
            out[rid] = (planned, state)
        return out

    def plan_progress(
        self,
        plans: list[Plan],
        earned: float | None = None,
        in_progress: float | None = None,
    ) -> Answer:
        """What doing a plan leaves on the audit; several plans are compared line by line."""
        targets = self.student.open_requirements
        if not plans:
            return Answer(
                f"There's no plan yet. Tell me what you want for {self.term_label} and I'll "
                "build some.",
                [Suggestion("Plan next semester", "Plan my next semester")],
            )
        total = len(targets)
        if len(plans) > 1:
            lines, finished = [], {}
            for plan in plans:
                states = [s for _, s in self.progress(plan.contributions).values()]
                done = states.count("done")
                helped = states.count("partial") + states.count("counts")
                finished[plan.name] = done
                lines.append(
                    f"{plan.name} ({plural(plan.credits, 'credit')}) finishes {done} of your "
                    f"{total} open requirements"
                    + (f", helps with {helped} more" if helped else "")
                    + f" and leaves {total - done} open."
                )
            best = max(finished.values())
            leaders = [name for name, n in finished.items() if n == best]
            if len(leaders) == 1:
                lines.append(f"{leaders[0]} finishes the most.")
            elif len(leaders) == len(plans):
                lines.append(f"They all finish {best}, so pick by the times that suit you.")
            else:
                lines.append(f"{listing(leaders)} tie for the most ({best}).")
            suggestions = [
                Suggestion(f"More on {p.name}", f"If I do {p.name}, what's left?")
                for p in plans[:3]
            ]
            return Answer("\n".join(lines), suggestions)
        plan = plans[0]
        progress = self.progress(plan.contributions)
        done = [r for r, (_, s) in progress.items() if s == "done"]
        partial = [r for r, (_, s) in progress.items() if s == "partial"]
        counts = [r for r, (_, s) in progress.items() if s == "counts"]
        still = [r for r in targets if r not in done]

        def name(rid: str) -> str:
            return short(targets[rid].title)

        opening = (
            f"With {plan.name} ({plural(plan.credits, 'credit')}), you'd finish {len(done)} of "
            f"your {total} open requirements"
        )
        if partial or counts:
            opening += f" and make progress on {len(partial) + len(counts)} more"
        lines = [opening + f", so {len(still)} would still be open."]
        if done:
            lines.append(f"Finished: {listing([name(r) for r in done])}.")
        if partial:
            parts = []
            for r in partial:
                t = targets[r]
                planned = progress[r][0]
                unit = t.unit if t.unit == "credits" else "courses"
                parts.append(f"{name(r)} ({planned:g} of {t.needed:g} {unit})")
            lines.append(f"Partly done: {listing(parts)}.")
        if counts:
            lines.append(f"Also counts toward: {listing([name(r) for r in counts])}.")
        untouched = [r for r in still if r not in partial and r not in counts]
        if untouched:
            lines.append(f"Not touched by {plan.name}: {listing([name(r) for r in untouched])}.")
        if earned is not None:
            have = earned + (in_progress or 0)
            source = f"{earned:g} earned" + (
                f", {in_progress:g} in progress" if in_progress else ""
            )
            lines.append(
                f"You'd be at {plural(have + plan.credits, 'credit')} ({source} and "
                f"{plan.credits:g} from {plan.name})."
            )
        shared = [c for c in plan.courses if sum(c in cs for cs in plan.contributions.values()) > 1]
        if shared:
            lines.append(
                f"{listing(shared, 3)} count toward more than one requirement here; your audit "
                "decides whether a course may count twice."
            )
        suggestions = [Suggestion("Compare my plans", "Compare my plans")]
        if untouched:
            suggestions.append(
                Suggestion(
                    f"What counts for {name(untouched[0])}?",
                    f"What courses count for {name(untouched[0])}?",
                )
            )
        return Answer("\n".join(lines), suggestions)


@dataclass(frozen=True)
class Plan:
    """One schedule option, as the answers need it."""

    name: str  # "Plan A"
    credits: float
    courses: list[str]
    contributions: dict[str, list[str]]  # requirement id -> this plan's courses that count


def requirement_hint(advisor: Advisor, rid: str, target: RequirementTarget) -> str | None:
    """A short "ECON 1400 · 3 cr" / "3 cr each" note for the web's requirement lists."""
    codes = advisor.requirement_courses().get(rid, set())
    each = advisor.credits_each(codes)
    one = target.needed in (None, 1) and target.unit != "credits"
    if one and len(codes) == 1 and each:  # exactly this course is what's needed
        return f"{next(iter(codes))} · {each[0]:g} cr"
    if each and target.unit == "courses":
        return f"{each[0]:g} cr each" if each[0] == each[1] else f"{each[0]:g}–{each[1]:g} cr each"
    return None
