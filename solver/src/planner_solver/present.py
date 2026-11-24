"""Deterministic text for solver results. Every fact comes from solver or catalog data;
the chat layer may add connective sentences, never facts."""

from __future__ import annotations

from planner_solver.describe import describe
from planner_solver.domain import RequirementTarget, StudentTerm, TermData, when
from planner_solver.spec import Constraint, ConstraintSpec
from planner_solver.term import Schedule, TermResult

NOTE_CHARS = 140
SHOWN = 3  # schedules shown; the solver finds up to five (so a fix can say "5+")


def label(
    constraint: Constraint,
    term: TermData | None = None,
    targets: dict[str, RequirementTarget] | None = None,
) -> str:
    """What the rule does, in plain words (the student's own words can be fragments)."""
    return describe(constraint, term, targets)


def render_result(
    result: TermResult,
    spec: ConstraintSpec,
    term: TermData,
    student: StudentTerm,
    listing: bool = True,  # False: the schedules are drawn elsewhere (the web canvas)
) -> str:
    by_id = {c.id: c for c in spec.constraints}
    lines: list[str] = [f"note: {w}" for w in result.warnings]
    if result.status == "infeasible":
        return "\n".join(lines + _conflict(result, by_id, term, student))

    if listing:
        for n, schedule in enumerate(result.schedules[:SHOWN], start=1):
            lines += _schedule(n, schedule, result, spec, term, student)
    else:
        shown = min(len(result.schedules), SHOWN)
        lines.append(f"Found {shown} schedule{'s' if shown != 1 else ''}: see the calendar.")
    grouped: dict[tuple[str, ...], list[str]] = {}
    for missed in result.missed:  # one line per rule that causes it
        target = student.open_requirements[missed.req_id]
        only = "the only option" if len(missed.courses) == 1 else "the only options"
        grouped.setdefault(tuple(missed.blocked_by), []).append(
            f"{' and '.join(missed.courses)} ({only} for {target.title})"
        )
    for blocked_by, lost in grouped.items():
        rules = " and ".join(label(by_id[c], term, student.open_requirements) for c in blocked_by)
        lines.append(f"Heads up: {rules} rules out {'; '.join(lost)}.")
    if result.estimates:
        said = ", ".join(label(by_id[c], term) for c in result.estimates)
        lines.append(f"note: {said} is estimated from course levels and labs.")
    return "\n".join(lines)


def _conflict(
    result: TermResult, by_id: dict[str, Constraint], term: TermData, student: StudentTerm
) -> list[str]:
    def said(cid: str) -> str:
        return label(by_id[cid], term, student.open_requirements)

    if len(result.conflict) == 1:
        lines = [f"I can't make this work this term: {said(result.conflict[0])}."]
    else:
        lines = ["These can't all hold at once:"]
        lines += [f"  • {said(cid)}" for cid in result.conflict]
    facts = [fact for cid in result.conflict for fact in result.reasons.get(cid, [])]
    if facts:
        lines.append("Why: " + "; ".join(facts) + ".")
    if result.relaxations and len(result.conflict) > 1:
        lines.append("Ways to fix it (least important first):")
        for n, r in enumerate(result.relaxations, start=1):
            outcome = _unlocked(r.schedules_unlocked)
            lines.append(f"  {n}. Drop “{said(r.constraint_id)}” → {outcome}")
    elif result.relaxations:
        lines.append(f"  1. Drop it → {_unlocked(result.relaxations[0].schedules_unlocked)}")
    return lines


def _unlocked(count: int) -> str:
    if not count:
        return "still no schedule"
    return f"{count}{'+' if count >= 5 else ''} schedule{'s' if count != 1 else ''}"


def _schedule(
    n: int,
    schedule: Schedule,
    result: TermResult,
    spec: ConstraintSpec,
    term: TermData,
    student: StudentTerm,
) -> list[str]:
    first = result.schedules[0]
    added = [s for s in schedule.sections if s not in first.sections]
    removed = [s for s in first.sections if s not in schedule.sections]
    as_diff = n > 1 and max(len(added), len(removed)) <= len(schedule.sections) / 2
    if as_diff:
        lines = [f"Schedule {n} · {schedule.credits:g} credits: like schedule 1, but"]
        lines += [f"  − {sid}  {term.courses[_course(sid, term)].title}" for sid in removed]
        shown, mark = added, "  + "
    else:
        lines = [f"Schedule {n} · {schedule.credits:g} credits"]
        shown, mark = schedule.sections, "  "
    explained: set[str] = set()  # a course with a lecture and a lab says what it counts for once
    for sid in shown:
        lines += _section(
            sid, mark, schedule, result, spec, term, student.open_requirements, explained
        )
    if schedule.soft_missed:
        by_id = {c.id: c for c in spec.constraints}
        missed = "; ".join(label(by_id[c]) for c in schedule.soft_missed)
        lines.append(f"  preferences not met: {missed}")
    return lines


def _course(section_id: str, term: TermData) -> str:
    return next(s.course for s in term.sections if s.section_id == section_id)


def _section(
    sid: str,
    mark: str,
    schedule: Schedule,
    result: TermResult,
    spec: ConstraintSpec,
    term: TermData,
    targets: dict[str, RequirementTarget],
    explained: set[str],
) -> list[str]:
    s = next(x for x in term.sections if x.section_id == sid)
    course = term.courses[s.course]
    who = ", ".join(s.instructors) or "instructor TBA"
    lines = [f"{mark}{sid}  {course.title} ({course.credits:g} cr)  {when(s)}  · {who}"]
    if s.course in explained:
        return lines
    explained.add(s.course)
    for reason in result.prereq_unchecked.get(s.course, []):
        short = reason if len(reason) <= NOTE_CHARS else reason[: NOTE_CHARS - 1] + "…"
        lines.append(f"      ⚠ {short}")
    counts = [  # in audit order
        _progress(targets[rid], schedule.contributions[rid], term)
        for rid in targets
        if s.course in schedule.contributions.get(rid, [])
    ]
    requested = {c.params.get("course") for c in spec.constraints if c.type == "include_course"}
    if counts:
        lines.append(f"      → {'; '.join(counts)}")
    elif s.course in requested:
        lines.append("      → you asked for this; it doesn't count toward an open requirement")
    else:
        lines.append("      → doesn't count toward an open requirement")
    return lines


def _progress(target: RequirementTarget, courses: list[str], term: TermData) -> str:
    """'CS electives (6 of 6 credits)' from what this schedule's courses contribute."""
    if target.unit == "credits" and target.needed:
        got = sum(term.courses[c].credits for c in courses)
        return f"{target.title} ({min(got, target.needed):g} of {target.needed:g} credits)"
    if target.unit == "courses" and target.needed:
        noun = "class" if target.needed == 1 else "classes"
        return f"{target.title} ({min(len(courses), target.needed):g} of {target.needed:g} {noun})"
    return target.title
