import json
from pathlib import Path

from planner_ingest.uvm.parse import classify_method, parse_term


def meeting(day: str, start: str, end: str) -> dict[str, str]:
    return {"meet_day": day, "start_time": start, "end_time": end}


def row(
    code: str, crn: str, no: str, schd: str, meets: list[dict[str, str]], instr: str = "A. Prof"
):
    return {
        "code": code,
        "title": code + " title",
        "crn": crn,
        "no": no,
        "schd": schd,
        "meetingTimes": json.dumps(meets),
        "instr": instr,
    }


def details(
    code: str, crn: str, method: str, hours: str = "3", attrs: str = "", stat: dict | None = None
):
    sections = [
        {"crn": {"val": c}, "section_stat": {"val": s}, "instr": {"val": "A. Prof"}}
        for c, s in (stat or {}).items()
    ]
    return {
        "code": code,
        "crn": crn,
        "instructional_method": method,
        "hours_html": hours,
        "class_attributes_descr": attrs,
        "all_sections__data": json.dumps({"sections": sections}),
    }


def write(tmp: Path, rows, dets) -> Path:
    (tmp / "details").mkdir(parents=True)
    (tmp / "search_all.json").write_text(json.dumps({"results": rows}))
    for d in dets:
        (tmp / "details" / f"{d['code'].replace(' ', '_')}.json").write_text(json.dumps(d))
    return tmp


def test_parse_sections_meetings_attributes_and_learned_codes(tmp_path: Path) -> None:
    rows = [
        row("CS 1210", "1", "A", "L", [meeting("1", "1625", "1740"), meeting("3", "1625", "1740")]),
        row("CS 1210", "2", "OL1", "X", []),
        row("BIOL 1400", "3", "A", "L", [meeting("0", "0830", "0920")]),
        row("BIOL 1400", "4", "L01", "B", [meeting("3", "1315", "1615")]),
        row("BIOL 1450", "5", "A", "B", [meeting("2", "1315", "1615")]),
        row("CS 4990", "6", "A", "T", []),
        row("ENGL 1001", "7", "A", "Q", []),
    ]
    dets = [
        details(
            "CS 1210",
            "1",
            "Lecture",
            attrs="<ul><li>Quantitative and Data Literacy (QD)</li></ul>",
            stat={"1": "Open", "2": "Closed"},
        ),
        details("BIOL 1400", "3", "Lecture", hours="4"),
        details("BIOL 1450", "5", "Laboratory", hours="1 - 2"),
        details("CS 4990", "6", "Independent Study", hours="1 - 6"),
        details("ENGL 1001", "7", "Puppetry"),
    ]
    write(tmp_path, rows, dets)
    term, report = parse_term(tmp_path, "202701")

    by_id = {s.section_id: s for s in term.sections}
    lec = by_id["CS 1210 A"]
    assert [(m.days, m.start, m.end) for m in lec.meetings] == [
        (("T", "R"), 16 * 60 + 25, 17 * 60 + 40)
    ]
    assert lec.seats_open is None and by_id["CS 1210 OL1"].seats_open == 0  # Closed
    assert term.courses["CS 1210"].attributes == frozenset({"QD"})
    assert term.courses["BIOL 1450"].credits == 1  # variable credit: the minimum
    assert by_id["BIOL 1400 L01"].component == "LAB"  # 'B' learned from BIOL 1450 = Laboratory
    assert by_id["BIOL 1400 A"].modality == "in_person"
    assert "CS 4990 A" not in by_id and report.arranged_sections == 1  # never auto-scheduled
    assert by_id["ENGL 1001 A"].modality is None  # unknown method: not guessed
    assert report.unknown_methods == {"Puppetry": 1}
    assert term.prereqs_loaded is False


def test_online_section_code_learned_only_when_seen(tmp_path: Path) -> None:
    rows = [row("CS 1210", "1", "A", "X", [])]
    write(tmp_path, rows, [details("CS 1210", "1", "Online Asynchronous")])
    term, _ = parse_term(tmp_path, "202701")
    assert term.sections[0].modality == "online"


def test_method_rules() -> None:
    assert classify_method("Hybrid (Online and In Class)") == ("LEC", "hybrid")
    assert classify_method("Lecture and Lab") == ("LEC", "in_person")
    assert classify_method("Laboratory") == ("LAB", "in_person")
    assert classify_method("Thesis/Dissertation") == ("ARR", None)


def test_load_term_attaches_parsed_prerequisites(tmp_path: Path) -> None:
    from planner_ingest.cli import load_term
    from planner_solver.domain import CoursePrereq

    term_dir = write(
        tmp_path / "202701",
        [row("CS 2240", "1", "A", "L", []), row("CS 1210", "2", "A", "L", [])],
        [details("CS 2240", "1", "Lecture"), details("CS 1210", "2", "Lecture")],
    )
    assert load_term("202701", tmp_path).prereqs_loaded is False
    (term_dir / "prereqs.json").write_text(
        json.dumps(
            {
                "CS 2240": {
                    "kind": "course",
                    "code": "CS 2100",
                    "min_grade": None,
                    "concurrent_ok": False,
                }
            }
        )
    )
    term = load_term("202701", tmp_path)
    assert term.prereqs_loaded is True
    assert term.courses["CS 2240"].prereq == CoursePrereq(kind="course", code="CS 2100")
    assert term.courses["CS 1210"].prereq is None


def test_lecture_and_discussion_is_a_lecture() -> None:
    assert classify_method("Lecture and Discussion") == ("LEC", "in_person")
    assert classify_method("Discussion") == ("DIS", "in_person")


def test_schd_meaning_is_the_dominant_one_with_enough_evidence(tmp_path: Path) -> None:
    rows, dets = [], []
    for i in range(20):  # 19 hybrid courses + 1 online one, all coded "V"
        code = f"HY {1000 + i}"
        rows.append(row(code, str(i), "A", "V", []))
        dets.append(
            details(
                code, str(i), "Online Asynchronous" if i == 0 else "Hybrid (Online and In Class)"
            )
        )
    rows += [row("ODD 1000", "90", "A", "Q", []), row("ODD 1001", "91", "A", "Q", [])]
    dets += [details("ODD 1000", "90", "Lecture"), details("ODD 1001", "91", "Practicum")]
    write(tmp_path, rows, dets)
    term, report = parse_term(tmp_path, "202701")
    assert {s.modality for s in term.sections if s.course.startswith("HY")} == {"hybrid"}  # 95%
    assert report.ambiguous_schd == ["Q"]  # 1 lecture vs 1 practicum: too little to decide


def test_load_term_marks_review_queue_courses_unknown_not_free(tmp_path: Path) -> None:
    from planner_ingest.cli import load_term
    from planner_solver.domain import UnparsedPrereq

    rows, dets = [row("CS 3200", "1", "A", "L", [])], [details("CS 3200", "1", "Lecture")]
    term_dir = write(tmp_path / "202701", rows, dets)
    (term_dir / "prereqs.json").write_text("{}")
    queued = [
        {"code": "CS 3200", "notes": "Prereq: CS 2240 & 2250 ?", "reason": "flagged ambiguous"}
    ]
    (term_dir / "prereq_review.json").write_text(json.dumps(queued))
    prereq = load_term("202701", tmp_path).courses["CS 3200"].prereq
    assert prereq == UnparsedPrereq(kind="unparsed", text="Prereq: CS 2240 & 2250 ?")


def test_owner_rule_senior_seminar_requires_senior_standing(tmp_path: Path) -> None:
    from planner_ingest.cli import load_term
    from planner_solver.domain import AllPrereq, CoursePrereq, StandingPrereq

    rows = [row("CS 3920", "1", "A", "L", []), row("HST 4990", "2", "A", "L", [])]
    dets = [details("CS 3920", "1", "Lecture"), details("HST 4990", "2", "Lecture")]
    term_dir = write(tmp_path / "202701", rows, dets)
    raw = json.loads((term_dir / "search_all.json").read_text())
    raw["results"][0]["title"] = "Senior Seminar"
    raw["results"][1]["title"] = "History Senior Seminar"
    (term_dir / "search_all.json").write_text(json.dumps(raw))
    tree = {"kind": "course", "code": "HST 2000", "min_grade": None, "concurrent_ok": False}
    (term_dir / "prereqs.json").write_text(json.dumps({"HST 4990": tree}))
    courses = load_term("202701", tmp_path).courses
    senior = StandingPrereq(kind="standing", minimum="senior")
    assert courses["CS 3920"].prereq == senior
    assert courses["HST 4990"].prereq == AllPrereq(
        kind="and", items=[CoursePrereq(kind="course", code="HST 2000"), senior]
    )


def test_single_attribute_given_as_plain_text() -> None:
    from planner_ingest.uvm.parse import _attributes

    assert _attributes("Social Sciences (S1)") == frozenset({"S1"})
    assert _attributes("<ul><li>Arts (AH1)</li><li>Humanities (AH3)</li></ul>") == frozenset(
        {"AH1", "AH3"}
    )
    assert _attributes("Humanities (AH3)<br/>Diversity (D2)") == frozenset({"AH3", "D2"})
    assert _attributes("") == frozenset()


def test_placeholder_instructor_names_are_cleaned(tmp_path: Path) -> None:
    rows = [row("CS 3990", "1", "A", "L", [], instr=".. Staff")]
    write(tmp_path, rows, [details("CS 3990", "1", "Lecture")])  # no section meta: row name used
    term, _ = parse_term(tmp_path, "202701")
    assert term.sections[0].instructors == ("Staff",)
