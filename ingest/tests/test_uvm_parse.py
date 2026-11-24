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
