"""Deterministic text for solver results. Every fact comes from solver or catalog data;
the chat layer may add connective sentences, never facts."""

from __future__ import annotations

from planner_solver.domain import RequirementTarget, Section, StudentTerm, TermData
from planner_solver.spec import Constraint, ConstraintSpec
from planner_solver.term import TermResult

NOTE_CHARS = 140


def _clock(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def _when(section: Section) -> str:
    if not section.meetings:
        return "no set meeting time" + (" (online)" if section.modality == "online" else "")
    return ", ".join(
        f"{''.join(m.days)} {_clock(m.start)}–{_clock(m.end)}" for m in section.meetings
    )


def _label(constraint: Constraint) -> str:
    if constraint.source_text:
        return f"“{constraint.source_text}”"
    detail = ", ".join(f"{k} {v}" for k, v in constraint.params.items())
    return f"{constraint.type.replace('_', ' ')} ({detail})"


def render_result(
    result: TermResult, spec: ConstraintSpec, term: TermData, student: StudentTerm
) -> str:
    by_id = {c.id: c for c in spec.constraints}
    sections = {s.section_id: s for s in term.sections}
    lines: list[str] = [f"note: {w}" for w in result.warnings]
    if result.status == "infeasible":
        lines.append("These requests can't all hold at once:")
        lines += [f"  • {_label(by_id[cid])}" for cid in result.conflict]
        if result.relaxations:
            lines.append("Ways to relax them (least important first):")
            for n, r in enumerate(result.relaxations, start=1):
                count = r.schedules_unlocked
                outcome = (
                    f"{count}{'+' if count >= 5 else ''} schedule{'s' if count != 1 else ''}"
                    if count
                    else "still no schedule"
                )
                lines.append(f"  {n}. Drop {_label(by_id[r.constraint_id])} → {outcome}")
        return "\n".join(lines)

    targets = student.open_requirements
    requested = {c.params.get("course") for c in spec.constraints if c.type == "include_course"}
    for n, schedule in enumerate(result.schedules, start=1):
        lines.append(f"Schedule {n} · {schedule.credits:g} credits")
        for sid in schedule.sections:
            s = sections[sid]
            course = term.courses[s.course]
            who = ", ".join(s.instructors) or "instructor TBA"
            lines.append(f"  {sid}  {course.title} ({course.credits:g} cr)  {_when(s)}  · {who}")
            for reason in result.prereq_unchecked.get(s.course, []):
                short = reason if len(reason) <= NOTE_CHARS else reason[: NOTE_CHARS - 1] + "…"
                lines.append(f"      ⚠ {short}")
            counts = [  # in audit order
                _progress(targets[rid], schedule.contributions[rid], term)
                for rid in targets
                if s.course in schedule.contributions.get(rid, [])
            ]
            if counts:
                lines.append(f"      → {'; '.join(counts)}")
            elif s.course in requested:
                lines.append(
                    "      → you asked for this; it doesn't count toward an open requirement"
                )
        if schedule.soft_missed:
            missed = "; ".join(_label(by_id[c]) for c in schedule.soft_missed)
            lines.append(f"  preferences not met: {missed}")
    if result.estimates:
        lines.append("estimates: " + ", ".join(_label(by_id[c]) for c in result.estimates))
    return "\n".join(lines)


def _progress(target: RequirementTarget, courses: list[str], term: TermData) -> str:
    """'CS electives (6 of 6 credits)' from what this schedule's courses contribute."""
    if target.unit == "credits" and target.needed:
        got = sum(term.courses[c].credits for c in courses)
        return f"{target.title} ({min(got, target.needed):g} of {target.needed:g} credits)"
    if target.unit == "courses" and target.needed:
        noun = "class" if target.needed == 1 else "classes"
        return f"{target.title} ({min(len(courses), target.needed):g} of {target.needed:g} {noun})"
    return target.title
