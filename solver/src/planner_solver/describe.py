"""Plain-English wording of constraints, built only from the validated spec and catalog.

The chat shows this instead of the LLM's restatement, so the student always sees exactly
what the solver is working with, nothing dropped and nothing added.
"""

from __future__ import annotations

from planner_solver.domain import RequirementTarget, TermData, clock
from planner_solver.spec import Constraint, ConstraintSpec, minutes

DAY_NAMES = {
    "M": "Monday",
    "T": "Tuesday",
    "W": "Wednesday",
    "R": "Thursday",
    "F": "Friday",
    "S": "Saturday",
    "U": "Sunday",
}
COMPARE = {"at_least": "at least", "at_most": "at most", "exactly": "exactly"}
DEFAULT_IDS = frozenset({"default_credits", "default_load_preference"})


def _time(hhmm: str) -> str:
    return clock(minutes(hhmm))


def _days(days: list[str] | None) -> str:
    return "" if not days else " on " + ", ".join(DAY_NAMES[d] + "s" for d in days)


def _n(count: float, noun: str) -> str:
    plural = noun + ("es" if noun.endswith(("s", "ss")) else "s")
    return f"{count:g} {noun if count == 1 else plural}"


def _course(code: str, term: TermData | None) -> str:
    course = term.courses.get(code) if term else None
    return f"{code} ({course.title})" if course else code


def describe(
    con: Constraint,
    term: TermData | None = None,
    targets: dict[str, RequirementTarget] | None = None,
) -> str:
    try:
        return _describe(con, term, targets or {})
    except (KeyError, TypeError, ValueError):  # params that didn't validate: say it generically
        detail = ", ".join(f"{k} {v}" for k, v in con.params.items())
        return f"{con.type.replace('_', ' ')} ({detail})"


def _describe(con: Constraint, term: TermData | None, targets: dict[str, RequirementTarget]) -> str:
    p, kind = con.params, con.type
    if kind == "include_course":
        return f"take {_course(p['course'], term)}"
    if kind == "exclude_course":
        return f"not {_course(p['course'], term)}"
    if kind == "satisfy_requirement":
        titles = [targets[r].title if r in targets else r for r in p["req_ids"]]
        what = " / ".join(titles)
        if len(titles) > 1:
            what = f"{p.get('count', 1)} of: {what}"
        return f"something for {what}" + (" (separate courses)" if p.get("distinct") else "")
    if kind == "course_attribute":
        return f"{COMPARE[p['comparator']]} {_n(p['count'], p['attribute'] + ' course')}"
    if kind == "level_distribution":
        return f"{COMPARE[p['comparator']]} {_n(p['count'], str(p['level']) + '-level course')}"
    if kind == "subject_limit":
        return f"{COMPARE[p['comparator']]} {_n(p['count'], p['subject'] + ' course')}"
    if kind == "difficulty_load":
        return f"a {p['target']} workload"
    if kind == "credit_range":
        low, high = p["min"], p["max"]
        if con.id == "default_load_preference":
            return f"a typical load ({low:g}–{high:g} credits)"
        if con.id == "default_credits":
            return f"a full-time load ({low:g}–{high:g} credits)"
        return _n(low, "credit") if low == high else f"{low:g}–{high:g} credits"
    if kind == "course_count_range":
        low, high = p["min"], p["max"]
        if low == high:
            return _n(high, "class")
        return f"at most {_n(high, 'class')}" if low <= 1 else f"{low:g}–{high:g} classes"
    if kind == "no_earlier_than":
        return f"nothing before {_time(p['time'])}{_days(p.get('days'))}"
    if kind == "no_later_than":
        return f"done by {_time(p['time'])}{_days(p.get('days'))}"
    if kind == "free_day":
        return f"{DAY_NAMES[p['day']]}s free"
    if kind == "free_block":
        label = f" ({p['label']})" if p.get("label") else ""
        return f"{DAY_NAMES[p['day']]}s {_time(p['start'])}–{_time(p['end'])} free{label}"
    if kind == "max_days_on_campus":
        return f"at most {_n(p['count'], 'day')} on campus"
    if kind == "max_consecutive_classes":
        return f"no more than {_n(p['count'], 'class')} in a row"
    if kind == "max_consecutive_labs":
        return f"no more than {_n(p['count'], 'lab')} in a row"
    if kind == "max_labs_per_day":
        return f"at most {_n(p['count'], 'lab')} a day"
    if kind == "gap_between_classes":
        parts = []
        if p.get("min_minutes") is not None:
            parts.append(f"at least {p['min_minutes']} min between classes")
        if p.get("max_minutes") is not None:
            parts.append(f"gaps of at most {p['max_minutes']} min")
        return " and ".join(parts) or "gaps between classes"
    if kind == "compactness":
        return (
            "classes on as few days as possible"
            if p["direction"] == "compact"
            else ("classes spread across the week")
        )
    if kind == "instructor_preference":
        if p["polarity"] == "include":
            return (
                f"{p['course']} with {p['name']}"
                if p.get("course")
                else (f"a class with {p['name']}")
            )
        scope = f" for {p['course']}" if p.get("course") else ""
        return f"not with {p['name']}{scope}"
    if kind == "modality":
        fmt = p["format"].replace("_", "-")
        if p.get("comparator") is None:
            return f"only {fmt} classes"
        return f"{COMPARE[p['comparator']]} {_n(p['count'], fmt + ' class')}"
    if kind == "open_seats_only":
        return "only sections with open seats" if p["value"] else "full sections are fine"
    detail = ", ".join(f"{k} {v}" for k, v in p.items())
    return f"{kind.replace('_', ' ')} ({detail})"


def summary(
    spec: ConstraintSpec,
    term: TermData | None = None,
    targets: dict[str, RequirementTarget] | None = None,
) -> str:
    """One line: what the schedules below are built around, in the order the student said it."""
    said = [c for c in spec.constraints if c.id not in DEFAULT_IDS]
    parts = [
        describe(c, term, targets) + (" (if possible)" if c.enforcement == "soft" else "")
        for c in said
    ]
    load = next((c for c in spec.constraints if c.id == "default_credits"), None)
    if load:
        parts.append(describe(load))
    if not said:
        return (
            "Working with: "
            + "; ".join(parts)
            + (", aiming for the most progress on your requirements" if parts else "")
        )
    return "Working with: " + "; ".join(parts)
