"""Term mode: choose sections for one term with CP-SAT.

Every constraint becomes one "holds" literal h with h => (constraint satisfied).
- hard: h is a solver assumption, so infeasibility yields the conflicting constraint ids,
  shrunk to a minimal set by deletion;
- soft: h is rewarded in the objective with power-of-two weight scaling.
Physical rules are always on: no time overlaps, one section per component of a chosen course,
nothing unplannable (already taken / registered), prerequisites not definitely unmet.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import combinations
from typing import Literal

from ortools.sat.python import cp_model

from planner_solver.domain import (
    DAYS,
    Course,
    Section,
    StudentTerm,
    TermData,
    blocking_reasons,
    prereq_met,
    resolve_selector,
    unknown_reasons,
)
from planner_solver.spec import (
    PLAN_ONLY,
    WEIGHT_SCALE,
    CampusParams,
    CompactnessParams,
    Comparator,
    ConsecutiveParams,
    ConstraintSpec,
    CountParams,
    CourseAttributeParams,
    CourseParams,
    DifficultyLoadParams,
    FreeBlockParams,
    FreeDayParams,
    GapParams,
    InstructorParams,
    LevelDistributionParams,
    ModalityParams,
    OpenSeatsParams,
    RangeParams,
    SatisfyRequirementParams,
    SectionSizeParams,
    SubjectLimitParams,
    TimeBoundParams,
    TravelTimeParams,
    minutes,
    parse_params,
)

BACK_TO_BACK_MINUTES = 15  # gap at or under this counts as consecutive
MAX_SCHEDULES = 5
SOFT_SCALE = 1000  # soft-constraint rewards dominate the coverage tie-break
TIME_LIMIT_SECONDS = 10.0
SCARCE_COURSES = 2  # a requirement with at most this many eligible courses this term...
SCARCE_BONUS = 3  # ...gets its progress weighted this much more
UNVERIFIED_PENALTY = 3  # half a course's progress: breaks ties, never outweighs real progress
Lit = cp_model.IntVar


@dataclass(frozen=True)
class Slot:
    section: str
    day: str
    start: int
    end: int


@dataclass
class Schedule:
    sections: list[str]
    courses: list[str]
    credits: float
    soft_met: list[str]
    soft_missed: list[str]
    requirements_covered: list[str]
    contributions: dict[str, list[str]] = field(default_factory=dict)  # req_id -> chosen courses


@dataclass
class Relaxation:
    constraint_id: str
    weight: int
    schedules_unlocked: int


@dataclass
class TermResult:
    status: Literal["ok", "infeasible"]
    schedules: list[Schedule] = field(default_factory=list)
    conflict: list[str] = field(default_factory=list)  # minimal set of hard constraint ids
    relaxations: list[Relaxation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    estimates: list[str] = field(default_factory=list)  # constraint ids answered with a proxy
    # courses allowed though part of their prerequisite couldn't be verified -> why
    prereq_unchecked: dict[str, list[str]] = field(default_factory=dict)


def _normalize_name(name: str) -> tuple[str, str]:
    """('smith', 'john') from 'John Smith', 'Smith, John A', 'Professor John Smith'."""
    name = name.replace("Professor", "").replace("Prof.", "").replace("Dr.", "").strip()
    if "," in name:
        last, first = (part.strip() for part in name.split(",", 1))
    else:
        parts = name.split()
        last, first = parts[-1], " ".join(parts[:-1])
    first_word = first.replace(".", " ").split()[0] if first.strip() else ""
    return last.casefold(), first_word.casefold()


def instructor_matches(wanted: str, actual: str) -> bool:
    """Same last name, and compatible first names: full names must agree; an initial matches."""
    w_last, w_first = _normalize_name(wanted)
    a_last, a_first = _normalize_name(actual)
    if w_last != a_last:
        return False
    if not w_first or not a_first:
        return True
    if len(w_first) > 1 and len(a_first) > 1:
        return w_first == a_first
    return w_first[0] == a_first[0]


class _Ctx:
    def __init__(
        self,
        data: TermData,
        student: StudentTerm,
        sections: list[Section],
        requirement_courses: dict[str, set[str]],
        blocked: dict[str, list[str]],
    ) -> None:
        self.data = data
        self.student = student
        self.requirement_courses = requirement_courses
        self.blocked = blocked  # course -> why its prerequisite isn't met
        self.unchecked: set[str] = set()  # courses whose prerequisite couldn't be verified
        self.model = cp_model.CpModel()
        self.sections = sections
        self.x = {s.section_id: self.model.NewBoolVar(f"x[{s.section_id}]") for s in sections}
        self.by_course: dict[str, list[Section]] = {}
        for s in sections:
            self.by_course.setdefault(s.course, []).append(s)
        self.y = {c: self.model.NewBoolVar(f"y[{c}]") for c in self.by_course}
        self.slots = [
            Slot(s.section_id, day, m.start, m.end)
            for s in sections
            for m in s.meetings
            for day in m.days
        ]
        self.warnings: list[str] = []
        self.estimates: list[str] = []
        self.objective_terms: list[tuple[int, Lit]] = []
        self.current = ""  # id of the constraint being encoded
        self.assignments: dict[str, tuple[dict[str, Lit], bool]] = {}

    def course(self, code: str) -> Course:
        return self.data.courses[code]

    def y_or_false(self, code: str) -> Lit | int:
        return self.y.get(code, 0)

    def forbid(self, h: Lit, predicate: Callable[[Section], bool]) -> None:
        for s in self.sections:
            if predicate(s):
                self.model.AddImplication(h, self.x[s.section_id].Not())

    def compare(
        self, h: Lit, expr: cp_model.LinearExprT, comparator: Comparator, count: int
    ) -> None:
        if comparator == "at_least":
            self.model.Add(expr >= count).OnlyEnforceIf(h)
        elif comparator == "at_most":
            self.model.Add(expr <= count).OnlyEnforceIf(h)
        else:
            self.model.Add(expr == count).OnlyEnforceIf(h)

    def section_slots(self, day: str | None = None) -> list[Slot]:
        return [s for s in self.slots if day is None or s.day == day]


def _overlap(a: Slot, b: Slot) -> bool:
    return a.day == b.day and a.start < b.end and b.start < a.end


# -- encoders: each adds `h => constraint` ----------------------------------------------------


def _include(ctx: _Ctx, h: Lit, p: CourseParams) -> None:
    if p.course not in ctx.y:
        ctx.model.AddImplication(h, ctx.model.NewConstant(0))
        if p.course in ctx.student.unplannable_courses:
            ctx.warnings.append(f"{p.course} is already taken or registered")
        elif p.course in ctx.blocked:
            ctx.warnings.append(f"{p.course} is blocked: {'; '.join(ctx.blocked[p.course])}")
        else:
            ctx.warnings.append(f"{p.course} has no section this term")
        return
    ctx.model.AddImplication(h, ctx.y[p.course])


def _exclude(ctx: _Ctx, h: Lit, p: CourseParams) -> None:
    if p.course in ctx.y:
        ctx.model.AddImplication(h, ctx.y[p.course].Not())


def _satisfy(ctx: _Ctx, h: Lit, p: SatisfyRequirementParams) -> None:
    # u[c]: course c is counted toward this constraint (only if it is taken)
    candidates = (
        set().union(*(ctx.requirement_courses.get(r, set()) for r in p.req_ids)) & ctx.y.keys()
    )
    use = {c: ctx.model.NewBoolVar(f"use[{ctx.current}][{c}]") for c in candidates}
    for code, u in use.items():
        ctx.model.AddImplication(u, ctx.y[code])
    covered = []
    for req_id in p.req_ids:
        courses = ctx.requirement_courses.get(req_id, set()) & use.keys()
        z = ctx.model.NewBoolVar(f"cover[{ctx.current}][{req_id}]")
        if courses:
            ctx.model.AddBoolOr([use[c] for c in courses]).OnlyEnforceIf(z)
        else:
            ctx.model.Add(z == 0)
        covered.append(z)
    ctx.model.Add(sum(covered) >= p.count).OnlyEnforceIf(h)
    ctx.assignments[ctx.current] = (use, p.distinct)


def _distinct_assignments(ctx: _Ctx) -> None:
    """A course counted for a `distinct` constraint isn't also counted for another one."""
    for (use_a, distinct_a), (use_b, distinct_b) in combinations(ctx.assignments.values(), 2):
        if distinct_a or distinct_b:
            for code in use_a.keys() & use_b.keys():
                ctx.model.Add(use_a[code] + use_b[code] <= 1)


def _credit_range(ctx: _Ctx, h: Lit, p: RangeParams) -> None:
    total = sum(int(round(ctx.course(c).credits * 2)) * y for c, y in ctx.y.items())  # half-credits
    ctx.model.Add(total >= int(round(p.min * 2))).OnlyEnforceIf(h)
    ctx.model.Add(total <= int(round(p.max * 2))).OnlyEnforceIf(h)


def _course_count(ctx: _Ctx, h: Lit, p: RangeParams) -> None:
    count = sum(ctx.y.values())
    ctx.model.Add(count >= int(p.min)).OnlyEnforceIf(h)
    ctx.model.Add(count <= int(p.max)).OnlyEnforceIf(h)


def _days(days: list[str] | None) -> set[str]:
    return set(days) if days else set(DAYS)


def _no_earlier(ctx: _Ctx, h: Lit, p: TimeBoundParams) -> None:
    limit, days = minutes(p.time), _days(p.days)
    ctx.forbid(h, lambda s: any(m.start < limit and set(m.days) & days for m in s.meetings))


def _no_later(ctx: _Ctx, h: Lit, p: TimeBoundParams) -> None:
    limit, days = minutes(p.time), _days(p.days)
    ctx.forbid(h, lambda s: any(m.end > limit and set(m.days) & days for m in s.meetings))


def _free_day(ctx: _Ctx, h: Lit, p: FreeDayParams) -> None:
    ctx.forbid(h, lambda s: any(p.day in m.days for m in s.meetings))


def _free_block(ctx: _Ctx, h: Lit, p: FreeBlockParams) -> None:
    start, end = minutes(p.start), minutes(p.end)
    ctx.forbid(
        h, lambda s: any(p.day in m.days and m.start < end and start < m.end for m in s.meetings)
    )


def _instructor(ctx: _Ctx, h: Lit, p: InstructorParams) -> None:
    def teaches(s: Section) -> bool:
        return any(instructor_matches(p.name, name) for name in s.instructors)

    in_scope = [s for s in ctx.sections if p.course is None or s.course == p.course]
    if not any(teaches(s) for s in in_scope):
        ctx.warnings.append(
            f"no section matches instructor {p.name!r}" + (f" for {p.course}" if p.course else "")
        )
    if p.polarity == "exclude":
        for s in in_scope:
            if teaches(s):
                ctx.model.AddImplication(h, ctx.x[s.section_id].Not())
        return
    # include: at least one chosen section is taught by them (for that course, if given)
    targets = [ctx.x[s.section_id] for s in in_scope if teaches(s)]
    ctx.model.AddBoolOr(targets or [ctx.model.NewConstant(0)]).OnlyEnforceIf(h)


def _gap(ctx: _Ctx, h: Lit, p: GapParams) -> None:
    for day in DAYS:
        slots = ctx.section_slots(day)
        for a, b in combinations(slots, 2):
            if a.section == b.section:
                continue
            first, second = (a, b) if a.start <= b.start else (b, a)
            gap = second.start - first.end
            xa, xb = ctx.x[first.section], ctx.x[second.section]
            if p.min_minutes is not None and 0 <= gap < p.min_minutes:
                ctx.model.AddBoolOr([h.Not(), xa.Not(), xb.Not()])
            if p.max_minutes is not None and gap > p.max_minutes:
                between = [
                    ctx.x[u.section]
                    for u in slots
                    if u.section not in (first.section, second.section)
                    and u.start >= first.end
                    and u.end <= second.start
                ]
                ctx.model.AddBoolOr([h.Not(), xa.Not(), xb.Not(), *between])


def _chains(slots: list[Slot], length: int) -> Iterable[list[Slot]]:
    """Runs of `length` slots, each starting within BACK_TO_BACK_MINUTES of the last's end."""
    ordered = sorted(slots, key=lambda s: s.start)

    def extend(path: list[Slot]) -> Iterable[list[Slot]]:
        if len(path) == length:
            yield path
            return
        last = path[-1]
        for nxt in ordered:
            if (
                nxt.section not in {s.section for s in path}
                and 0 <= nxt.start - last.end <= BACK_TO_BACK_MINUTES
            ):
                yield from extend([*path, nxt])

    for slot in ordered:
        yield from extend([slot])


def _consecutive(ctx: _Ctx, h: Lit, p: ConsecutiveParams, labs_only: bool) -> None:
    labs = {s.section_id for s in ctx.sections if s.is_lab}
    for day in _days(p.days):
        slots = [s for s in ctx.section_slots(day) if not labs_only or s.section in labs]
        for chain in _chains(slots, p.count + 1):
            ctx.model.AddBoolOr([h.Not(), *(ctx.x[s.section].Not() for s in chain)])


def _labs_per_day(ctx: _Ctx, h: Lit, p: CountParams) -> None:
    for day in DAYS:
        labs = {s.section for s in ctx.section_slots(day)} & {
            s.section_id for s in ctx.sections if s.is_lab
        }
        if len(labs) > p.count:
            ctx.model.Add(sum(ctx.x[s] for s in labs) <= p.count).OnlyEnforceIf(h)


def _day_used(ctx: _Ctx) -> dict[str, Lit]:
    used = {}
    for day in DAYS:
        on_campus = {s.section for s in ctx.section_slots(day)} - {
            s.section_id for s in ctx.sections if s.modality == "online"
        }
        if on_campus:
            d = ctx.model.NewBoolVar(f"day[{day}]")
            ctx.model.AddMaxEquality(d, [ctx.x[s] for s in on_campus])
            used[day] = d
    return used


def _max_days(ctx: _Ctx, h: Lit, p: CountParams) -> None:
    used = _day_used(ctx)
    if used:
        ctx.model.Add(sum(used.values()) <= p.count).OnlyEnforceIf(h)


def _compactness(ctx: _Ctx, h: Lit, p: CompactnessParams, scale: int) -> None:
    # An optimisation goal, not a yes/no rule: fewer (or more) campus days, weighted.
    days = list(_day_used(ctx).values())
    sign = -1 if p.direction == "compact" else 1
    for d in days:
        ctx.objective_terms.append((sign * scale, d))


def _modality(ctx: _Ctx, h: Lit, p: ModalityParams) -> None:
    matching = {
        c for c, sections in ctx.by_course.items() if all(s.modality == p.format for s in sections)
    }
    if any(s.modality is None for s in ctx.sections):
        ctx.warnings.append("some sections have no modality data")
    if p.comparator is None or p.count is None:
        for c, y in ctx.y.items():
            if c not in matching:
                ctx.model.AddImplication(h, y.Not())
        return
    ctx.compare(h, sum(ctx.y[c] for c in matching), p.comparator, p.count)


def _open_seats(ctx: _Ctx, h: Lit, p: OpenSeatsParams) -> None:
    if p.value:
        ctx.forbid(h, lambda s: s.seats_open is not None and s.seats_open <= 0)


def _section_size(ctx: _Ctx, h: Lit, p: SectionSizeParams) -> None:
    ctx.forbid(h, lambda s: s.capacity is not None and s.capacity > p.max_enrollment)


def _campus(ctx: _Ctx, h: Lit, p: CampusParams) -> None:
    if p.polarity == "only":
        ctx.forbid(h, lambda s: s.campus is not None and s.campus != p.campus)
    else:
        ctx.forbid(h, lambda s: s.campus == p.campus)


def _travel(ctx: _Ctx, h: Lit, p: TravelTimeParams) -> None:
    campus = {s.section_id: s.campus for s in ctx.sections}
    for a, b in combinations(ctx.slots, 2):
        if a.day != b.day or a.section == b.section or campus[a.section] == campus[b.section]:
            continue
        first, second = (a, b) if a.start <= b.start else (b, a)
        if second.start - first.end < p.min_minutes_between_campuses:
            ctx.model.AddBoolOr([h.Not(), ctx.x[a.section].Not(), ctx.x[b.section].Not()])


def _attribute(ctx: _Ctx, h: Lit, p: CourseAttributeParams) -> None:
    hits = [y for c, y in ctx.y.items() if p.attribute in ctx.course(c).attributes]
    ctx.compare(h, sum(hits), p.comparator, p.count)


def _level(ctx: _Ctx, h: Lit, p: LevelDistributionParams) -> None:
    hits = [y for c, y in ctx.y.items() if ctx.course(c).level == p.level]
    ctx.compare(h, sum(hits), p.comparator, p.count)


def _subject(ctx: _Ctx, h: Lit, p: SubjectLimitParams) -> None:
    hits = [y for c, y in ctx.y.items() if ctx.course(c).subject == p.subject]
    ctx.compare(h, sum(hits), p.comparator, p.count)


def _difficulty(ctx: _Ctx, h: Lit, p: DifficultyLoadParams) -> None:
    """Estimate only: per-course score = level digit + 1 if it has a lab (avg compared to bands)."""

    def score(code: str) -> int:
        lab = any(s.is_lab for s in ctx.by_course[code])
        return ctx.course(code).level // 1000 + (1 if lab else 0)

    total = sum(2 * score(c) * y for c, y in ctx.y.items())  # 2x: integer half-steps
    count = sum(ctx.y.values())
    if p.target == "light":
        ctx.model.Add(total <= 5 * count).OnlyEnforceIf(h)  # average <= 2.5
    elif p.target == "heavy":
        ctx.model.Add(total >= 6 * count).OnlyEnforceIf(h)  # average >= 3
    else:
        ctx.model.Add(total >= 4 * count).OnlyEnforceIf(h)
        ctx.model.Add(total <= 6 * count).OnlyEnforceIf(h)


ENCODERS: dict[str, Callable[..., None]] = {
    "include_course": _include,
    "exclude_course": _exclude,
    "satisfy_requirement": _satisfy,
    "credit_range": _credit_range,
    "course_count_range": _course_count,
    "no_earlier_than": _no_earlier,
    "no_later_than": _no_later,
    "free_day": _free_day,
    "free_block": _free_block,
    "instructor_preference": _instructor,
    "gap_between_classes": _gap,
    "max_consecutive_classes": lambda ctx, h, p: _consecutive(ctx, h, p, labs_only=False),
    "max_consecutive_labs": lambda ctx, h, p: _consecutive(ctx, h, p, labs_only=True),
    "max_labs_per_day": _labs_per_day,
    "max_days_on_campus": _max_days,
    "modality": _modality,
    "open_seats_only": _open_seats,
    "section_size": _section_size,
    "campus": _campus,
    "travel_time": _travel,
    "course_attribute": _attribute,
    "level_distribution": _level,
    "subject_limit": _subject,
    "difficulty_load": _difficulty,
}
ESTIMATED = {"difficulty_load"}


# -- model building -----------------------------------------------------------------------------


def _eligible_sections(
    data: TermData, student: StudentTerm, spec: ConstraintSpec
) -> tuple[
    list[Section], dict[str, set[str]], list[str], dict[str, list[str]], dict[str, list[str]]
]:
    warnings: list[str] = []
    unchecked: dict[str, list[str]] = {}  # allowed, but part of the prerequisite is unverified
    blocked: dict[str, list[str]] = {}  # prerequisite definitely not met -> why
    requirement_courses: dict[str, set[str]] = {}
    for req_id, target in student.open_requirements.items():
        courses: set[str] = set()
        for selector in target.selectors:
            resolved = resolve_selector(selector, data.courses)
            if resolved is None:
                warnings.append(f"{req_id}: cannot interpret {selector!r}")
            else:
                courses |= resolved
        requirement_courses[req_id] = courses - set(target.excluded)
    wanted = set().union(*requirement_courses.values()) if requirement_courses else set()
    for c in spec.constraints:
        if c.type == "include_course":
            wanted.add(c.params.get("course", ""))
        if c.type == "instructor_preference" and c.params.get("course"):
            wanted.add(c.params["course"])
    sections = []
    for code in sorted(wanted - student.unplannable_courses):
        course = data.courses.get(code)
        if course is None:
            continue
        met = prereq_met(course.prereq, student)
        if met == "no":
            blocked[code] = blocking_reasons(course.prereq, student)
            continue
        if met == "unknown":
            unchecked[code] = unknown_reasons(course.prereq, student)
        sections.extend(s for s in data.sections if s.course == code)
    return sections, requirement_courses, warnings, unchecked, blocked


def _build(
    spec: ConstraintSpec,
    data: TermData,
    student: StudentTerm,
    sections: list[Section],
    requirement_courses: dict[str, set[str]],
    blocked: dict[str, list[str]],
    unchecked: dict[str, list[str]],
) -> tuple[_Ctx, dict[str, Lit]]:
    ctx = _Ctx(data, student, sections, requirement_courses, blocked)
    ctx.unchecked = set(unchecked)
    model = ctx.model
    # physical rules
    for code, course_sections in ctx.by_course.items():
        for component in {s.component for s in course_sections}:
            model.Add(
                sum(ctx.x[s.section_id] for s in course_sections if s.component == component)
                == ctx.y[code]
            )
    for a, b in combinations(ctx.slots, 2):
        if a.section != b.section and _overlap(a, b):
            model.AddBoolOr([ctx.x[a.section].Not(), ctx.x[b.section].Not()])

    holds: dict[str, Lit] = {}
    for constraint in spec.constraints:
        if constraint.type in PLAN_ONLY:
            ctx.warnings.append(
                f"{constraint.id}: {constraint.type} applies to plan mode only; ignored"
            )
            continue
        h = model.NewBoolVar(f"h[{constraint.id}]")
        ctx.current = constraint.id
        params = parse_params(constraint)
        scale = WEIGHT_SCALE[constraint.weight] * SOFT_SCALE
        if constraint.type == "compactness":
            _compactness(ctx, h, params, scale)
            model.Add(h == 1)
        else:
            ENCODERS[constraint.type](ctx, h, params)
        if constraint.type in ESTIMATED:
            ctx.estimates.append(constraint.id)
        holds[constraint.id] = h
        if constraint.enforcement == "soft":
            ctx.objective_terms.append((scale, h))
    _distinct_assignments(ctx)
    # tie-break: between equally good schedules, prefer courses whose prerequisites are verified
    for code in ctx.unchecked:
        if code in ctx.y:
            ctx.objective_terms.append((-UNVERIFIED_PENALTY, ctx.y[code]))
    # tie-break: progress toward each open requirement, capped at what it still needs
    for req_id, courses in requirement_courses.items():
        available = [c for c in courses if c in ctx.y]
        if not available:
            continue
        target = student.open_requirements[req_id]
        if target.unit == "credits" and target.needed:
            amount = sum(int(round(ctx.course(c).credits * 2)) * ctx.y[c] for c in available)
            cap, per_unit = int(round(target.needed * 2)), 1  # half-credits
        elif target.unit == "courses" and target.needed:
            amount, cap, per_unit = sum(ctx.y[c] for c in available), int(target.needed), 6
        else:
            amount, cap, per_unit = sum(ctx.y[c] for c in available), 1, 6
        progress = model.NewIntVar(0, cap, f"progress[{req_id}]")
        model.Add(progress <= amount)
        # bottlenecks first: a requirement only one or two courses can serve this term
        scarcity = SCARCE_BONUS if len(available) <= SCARCE_COURSES else 1
        ctx.objective_terms.append((per_unit * scarcity, progress))
    model.Maximize(sum(weight * lit for weight, lit in ctx.objective_terms))
    return ctx, holds


def _solve(ctx: _Ctx, assumptions: list[Lit]) -> tuple[cp_model.CpSolver, int]:
    ctx.model.ClearAssumptions()
    ctx.model.AddAssumptions(assumptions)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT_SECONDS
    solver.parameters.num_workers = 1  # assumptions-based cores need a single worker
    return solver, solver.Solve(ctx.model)


def _feasible(status: int) -> bool:
    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def _hard(spec: ConstraintSpec, holds: dict[str, Lit]) -> dict[str, Lit]:
    return {
        c.id: holds[c.id] for c in spec.constraints if c.enforcement == "hard" and c.id in holds
    }


def _minimal_core(ctx: _Ctx, hard: dict[str, Lit], core: list[str]) -> list[str]:
    """Deletion filter: drop each id whose removal keeps the set infeasible."""
    kept = list(core)
    for cid in list(core):
        trial = [c for c in kept if c != cid]
        _, status = _solve(ctx, [hard[c] for c in trial])
        if not _feasible(status):
            kept = trial
    return kept


def _schedules(
    ctx: _Ctx,
    spec: ConstraintSpec,
    holds: dict[str, Lit],
    assumptions: list[Lit],
    requirement_courses: dict[str, set[str]],
    limit: int,
) -> list[Schedule]:
    found: list[Schedule] = []
    for distinct_by in ("courses", "sections"):
        while len(found) < limit:
            solver, status = _solve(ctx, assumptions)
            if not _feasible(status):
                break
            chosen = [s for s in ctx.sections if solver.Value(ctx.x[s.section_id])]
            courses = sorted({s.course for s in chosen})
            soft = [c for c in spec.constraints if c.enforcement == "soft" and c.id in holds]
            found.append(
                Schedule(
                    sections=[s.section_id for s in chosen],
                    courses=courses,
                    credits=sum(ctx.course(c).credits for c in courses),
                    soft_met=[c.id for c in soft if solver.Value(holds[c.id])],
                    soft_missed=[c.id for c in soft if not solver.Value(holds[c.id])],
                    requirements_covered=sorted(
                        r for r, cs in requirement_courses.items() if cs & set(courses)
                    ),
                    contributions={
                        r: sorted(cs & set(courses))
                        for r, cs in sorted(requirement_courses.items())
                        if cs & set(courses)
                    },
                )
            )
            if distinct_by == "courses":
                lits = [ctx.y[c] for c in courses] + [
                    ctx.y[c].Not() for c in ctx.y if c not in courses
                ]
            else:
                ids = {s.section_id for s in chosen}
                lits = [ctx.x[s] if s in ids else ctx.x[s].Not() for s in ctx.x]
            ctx.model.AddBoolOr([lit.Not() for lit in lits])  # never this exact set again
        if len(found) >= limit:
            break
    return found


def solve_term(
    spec: ConstraintSpec, data: TermData, student: StudentTerm, limit: int = MAX_SCHEDULES
) -> TermResult:
    sections, requirement_courses, warnings, unchecked, blocked = _eligible_sections(
        data, student, spec
    )
    if not data.prereqs_loaded:
        warnings.insert(0, "prerequisites were not checked: catalog prerequisite data isn't loaded")
    ctx, holds = _build(spec, data, student, sections, requirement_courses, blocked, unchecked)
    warnings += ctx.warnings
    hard = _hard(spec, holds)

    solver, status = _solve(ctx, list(hard.values()))
    if not _feasible(status):
        by_index = {lit.Index(): cid for cid, lit in hard.items()}
        core = [
            by_index[i] for i in solver.SufficientAssumptionsForInfeasibility() if i in by_index
        ]
        core = _minimal_core(ctx, hard, core)
        weights = {c.id: c.weight for c in spec.constraints}
        relaxations = []
        for cid in sorted(core, key=lambda c: (weights[c], c)):
            ctx_r, holds_r = _build(
                spec, data, student, sections, requirement_courses, blocked, unchecked
            )
            hard_r = [lit for c, lit in _hard(spec, holds_r).items() if c != cid]
            unlocked = len(_schedules(ctx_r, spec, holds_r, hard_r, requirement_courses, limit))
            relaxations.append(Relaxation(cid, weights[cid], unlocked))
        return TermResult(
            "infeasible",
            conflict=core,
            relaxations=relaxations,
            warnings=warnings,
            estimates=ctx.estimates,
            prereq_unchecked=unchecked,
        )

    schedules = _schedules(ctx, spec, holds, list(hard.values()), requirement_courses, limit)
    return TermResult(
        "ok",
        schedules=schedules,
        warnings=warnings,
        estimates=ctx.estimates,
        prereq_unchecked=unchecked,
    )
