"""Raw Schedule-of-Courses JSON (cached by fetch.py) -> the solver's TermData.

Section kind and modality come from each course's instructional-method text (details call).
The search results' one-letter `schd` codes are undocumented, so their meaning is learned
from the representative sections whose method we know; a code with conflicting meanings
stays unknown. Arranged sections (independent study, thesis, internship...) are not
scheduled automatically. Prerequisites are not in this source: `prereqs_loaded` is False.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planner_solver.domain import Course, Meeting, Section, TermData

DAY_CODES = {"0": "M", "1": "T", "2": "W", "3": "R", "4": "F", "5": "S", "6": "U"}
# instructional method -> (component, modality); first match wins
METHOD_RULES: list[tuple[re.Pattern[str], str, str | None]] = [
    (
        re.compile(
            r"independent study|thesis|dissertation|internship|research|teaching assist"
            r"|practicum|field|clinical|co-?op|tutorial",
            re.I,
        ),
        "ARR",
        None,
    ),
    (re.compile(r"hybrid", re.I), "LEC", "hybrid"),  # before "online": "Hybrid (Online and ...)"
    (re.compile(r"online", re.I), "LEC", "online"),
    (re.compile(r"^lab", re.I), "LAB", "in_person"),
    (re.compile(r"^(discussion|recitation)", re.I), "DIS", "in_person"),
    (
        re.compile(r"lecture|seminar|studio|lab|ensemble|activity|private|lesson", re.I),
        "LEC",
        "in_person",
    ),
]
DOMINANT_SHARE = 0.95  # a schd letter takes its dominant meaning if this share of sections agree
MIN_EVIDENCE = 3
ATTRIBUTE_CODE = re.compile(r"\(([A-Z0-9]{1,6})\)\s*$")
TAG = re.compile(r"<[^>]+>")


@dataclass
class ParseReport:
    sections: int = 0
    courses: int = 0
    arranged_sections: int = 0
    unknown_methods: Counter[str] = field(default_factory=Counter)
    ambiguous_schd: list[str] = field(default_factory=list)
    missing_details: list[str] = field(default_factory=list)


def classify_method(method: str) -> tuple[str, str | None] | None:
    for pattern, component, modality in METHOD_RULES:
        if pattern.search(method):
            return component, modality
    return None


def _credits(hours: str) -> float | None:
    numbers = re.findall(r"\d+(?:\.\d+)?", TAG.sub(" ", hours or ""))
    return float(numbers[0]) if numbers else None  # variable credit: the minimum


def _attributes(html: str) -> frozenset[str]:
    """Attribute codes; several come as an <li> list, a single one as plain text."""
    items = re.findall(r"<li>(.*?)</li>", html or "", re.S) or re.split(r"<br\s*/?>|\n", html or "")
    return frozenset(
        m.group(1) for item in items if (m := ATTRIBUTE_CODE.search(TAG.sub("", item).strip()))
    )


def _meetings(raw: str) -> tuple[Meeting, ...]:
    slots = json.loads(raw) if raw else []
    grouped: dict[tuple[int, int], list[str]] = defaultdict(list)
    for slot in slots:
        day = DAY_CODES.get(str(slot.get("meet_day")))
        start, end = slot.get("start_time", ""), slot.get("end_time", "")
        if day is None or not (start.isdigit() and end.isdigit()):
            continue
        times = (int(start[:-2]) * 60 + int(start[-2:]), int(end[:-2]) * 60 + int(end[-2:]))
        grouped[times].append(day)
    return tuple(
        Meeting(days=tuple(sorted(set(days), key="MTWRFSU".index)), start=s, end=e)  # type: ignore[arg-type]
        for (s, e), days in sorted(grouped.items())
    )


def _sections_meta(details: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw = details.get("all_sections__data") or "{}"
    data = json.loads(raw) if isinstance(raw, str) else raw
    out = {}
    for row in data.get("sections", []):
        values = {k: (v["val"] if isinstance(v, dict) else v) for k, v in row.items()}
        out[str(values.get("crn"))] = values
    return out


def parse_term(cache_dir: Path, srcdb: str) -> tuple[TermData, ParseReport]:
    report = ParseReport()
    results = json.loads((cache_dir / "search_all.json").read_text())["results"]
    details: dict[str, dict[str, Any]] = {}
    for row in results:
        path = cache_dir / "details" / f"{row['code'].replace(' ', '_')}.json"
        if row["code"] not in details and path.exists():
            details[row["code"]] = json.loads(path.read_text())

    # learn what each schd letter means from representative sections
    seen: dict[str, Counter[tuple[str, str | None]]] = defaultdict(Counter)
    by_crn = {r["crn"]: r for r in results}
    for d in details.values():
        rep = by_crn.get(str(d.get("crn")))
        kind = classify_method(d.get("instructional_method") or "")
        if rep and kind:
            seen[rep["schd"]][kind] += 1
        elif d.get("instructional_method"):
            report.unknown_methods[d["instructional_method"]] += 1
    schd_kind: dict[str, tuple[str, str | None]] = {}
    for code, kinds in sorted(seen.items()):
        (kind, top), total = kinds.most_common(1)[0], sum(kinds.values())
        if len(kinds) == 1 or (total >= MIN_EVIDENCE and top / total >= DOMINANT_SHARE):
            schd_kind[code] = kind
        else:
            report.ambiguous_schd.append(code)

    courses: dict[str, Course] = {}
    sections: list[Section] = []
    for row in results:
        code = row["code"]
        d = details.get(code)
        if d is None:
            if code not in report.missing_details:
                report.missing_details.append(code)
            continue
        if code not in courses:
            credits = _credits(d.get("hours_html", ""))
            courses[code] = Course(
                code=code,
                title=row["title"],
                credits=credits or 0,
                attributes=_attributes(d.get("class_attributes_descr", "")),
            )
        component, modality = schd_kind.get(row["schd"], ("LEC", None))
        if component == "ARR":
            report.arranged_sections += 1
            continue
        meta = _sections_meta(d).get(row["crn"], {})
        status = (meta.get("section_stat") or "").casefold()
        names = (meta.get("instr") or row.get("instr") or "").split(",")
        instructors = tuple(n.strip(" .") for n in names if n.strip(" ."))
        sections.append(
            Section(
                section_id=f"{code} {row['no']}",
                course=code,
                component=component,
                meetings=_meetings(row.get("meetingTimes", "")),
                instructors=instructors,
                seats_open=0 if status.startswith("closed") else None,
                modality=modality,  # type: ignore[arg-type]
            )
        )
    report.sections, report.courses = len(sections), len(courses)
    term = TermData(term=srcdb, courses=courses, sections=tuple(sections), prereqs_loaded=False)
    return term, report


def _school_config() -> dict[str, Any]:
    from importlib import resources

    return json.loads(
        resources.files("planner_ingest.uvm").joinpath("capabilities.json").read_text()
    )


def load_capabilities() -> dict[str, str]:
    """Constraint types UVM's data can't support -> reason shown to the user (rule 8)."""
    return _school_config()["unavailable"]


def default_credit_range() -> tuple[float, float]:
    band = _school_config()["default_credit_range"]
    return band["min"], band["max"]
