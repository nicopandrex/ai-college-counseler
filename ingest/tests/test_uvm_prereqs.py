import json
from pathlib import Path

from planner_ingest.uvm.prereqs import has_prereq_text, parse_prereqs, prereq_notes
from planner_llm import CacheMode, JsonRequest, LLMGateway
from planner_solver.domain import AllPrereq, AnyPrereq, CoursePrereq, StandingPrereq, UnparsedPrereq


class Stub:
    name = "stub"

    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers = answers
        self.requests: list[JsonRequest] = []

    def complete_json(self, request: JsonRequest, model: str) -> str:
        self.requests.append(request)
        codes = [line.split(" | ")[0] for line in request.user.splitlines() if " | " in line]
        return json.dumps({"courses": [self.answers[c] for c in codes]})


def flatten(node, nodes):
    """Nested test tree -> the model's flat node list; returns the node id."""
    nid = f"n{len(nodes) + 1}"
    entry = {
        "id": nid,
        "kind": node["kind"],
        "children": [],
        "code": node.get("code"),
        "min_grade": node.get("min_grade"),
        "concurrent_ok": node.get("concurrent_ok", False),
        "minimum": node.get("minimum"),
        "text": node.get("text"),
    }
    nodes.append(entry)
    entry["children"] = [flatten(child, nodes) for child in node.get("items", [])]
    return nid


def course(code, node, ambiguous=False, note=None):
    nodes: list[dict] = []
    root = flatten(node, nodes) if node else None
    return {"code": code, "nodes": nodes, "root": root, "ambiguous": ambiguous, "note": note}


def test_prereq_text_is_detected_and_cleaned() -> None:
    assert has_prereq_text("Prereqs enforced by the system: BIOL 1400 and BIOL 1450")
    assert has_prereq_text("Junior/Senior standing.")
    assert not has_prereq_text("Open to Degree and PACE students")
    assert (
        prereq_notes({"clssnotes": "<p>Prerequisite: <b>CS 2100</b></p>"})
        == "Prerequisite: CS 2100"
    )


def test_trees_are_mapped_and_doubtful_ones_queued(tmp_path: Path) -> None:
    notes = {
        "CS 2240": "Prerequisite: CS 2100 with C- or better",
        "ALE 2010": (
            "Prereqs enforced by the system: BIOL 1400 and BIOL 1450 or BCOR 1400 and BCOR 1450"
        ),
        "ALE 1360": "Junior/Senior standing.",
        "ART 2000": "Prerequisite: portfolio review",
        "BAD 3000": "Prerequisite: CS 21OO",
    }
    answers = {
        "CS 2240": course(
            "CS 2240",
            {"kind": "course", "code": "CS 2100", "min_grade": "C-", "concurrent_ok": False},
        ),
        "ALE 2010": course(
            "ALE 2010",
            {
                "kind": "or",
                "items": [
                    {
                        "kind": "and",
                        "items": [
                            {
                                "kind": "course",
                                "code": "BIOL 1400",
                                "min_grade": None,
                                "concurrent_ok": False,
                            },
                            {
                                "kind": "course",
                                "code": "BIOL 1450",
                                "min_grade": None,
                                "concurrent_ok": False,
                            },
                        ],
                    },
                    {
                        "kind": "and",
                        "items": [
                            {
                                "kind": "course",
                                "code": "BCOR 1400",
                                "min_grade": None,
                                "concurrent_ok": False,
                            },
                            {
                                "kind": "course",
                                "code": "BCOR 1450",
                                "min_grade": None,
                                "concurrent_ok": False,
                            },
                        ],
                    },
                ],
            },
        ),
        "ALE 1360": course("ALE 1360", {"kind": "standing", "minimum": "junior"}),
        "ART 2000": course("ART 2000", {"kind": "unparsed", "text": "portfolio review"}),
        "BAD 3000": course(
            "BAD 3000",
            {"kind": "course", "code": "CS 21OO", "min_grade": None, "concurrent_ok": False},
        ),
    }
    gateway = LLMGateway(Stub(answers), "m", tmp_path / "c", CacheMode.LIVE)
    trees, review, _ = parse_prereqs(notes, gateway, batch_size=2)

    assert trees["CS 2240"] == CoursePrereq(kind="course", code="CS 2100", min_grade="C-")
    assert isinstance(trees["ALE 2010"], AnyPrereq) and isinstance(
        trees["ALE 2010"].items[0], AllPrereq
    )
    assert trees["ALE 1360"] == StandingPrereq(kind="standing", minimum="junior")
    assert {r["code"] for r in review} == {"ART 2000", "BAD 3000"}  # unparsed; malformed code
    assert all(r["notes"] for r in review)
    # an unparsed part evaluates as "unknown", so the tree is safe to use (and still reviewed)
    assert trees["ART 2000"] == UnparsedPrereq(kind="unparsed", text="portfolio review")
    assert "BAD 3000" not in trees  # a malformed code could match the wrong course: kept out


def test_a_skipped_course_is_asked_again_then_queued(tmp_path: Path) -> None:
    class Skipper(Stub):
        def complete_json(self, request: JsonRequest, model: str) -> str:
            self.requests.append(request)
            return json.dumps({"courses": []})

    skipper = Skipper({})
    gateway = LLMGateway(skipper, "m", tmp_path / "c", CacheMode.LIVE)
    trees, review, _ = parse_prereqs({"CS 3200": "Prerequisite: CS 2240"}, gateway)
    assert len(skipper.requests) == 2  # one re-ask for the skipped course
    assert "CS 3200" not in trees
    assert review == [
        {"code": "CS 3200", "notes": "Prerequisite: CS 2240", "reason": "not returned by the model"}
    ]


def test_a_skipped_course_answered_on_the_re_ask_is_kept(tmp_path: Path) -> None:
    class SkipOnce(Stub):
        def complete_json(self, request: JsonRequest, model: str) -> str:
            self.requests.append(request)
            if len(self.requests) == 1:
                return json.dumps({"courses": []})
            node = {"kind": "course", "code": "CS 2240", "min_grade": None, "concurrent_ok": False}
            return json.dumps({"courses": [course("CS 3200", node)]})

    gateway = LLMGateway(SkipOnce({}), "m", tmp_path / "c", CacheMode.LIVE)
    trees, review, _ = parse_prereqs({"CS 3200": "Prerequisite: CS 2240"}, gateway)
    assert trees["CS 3200"] == CoursePrereq(kind="course", code="CS 2240") and review == []


def test_deep_nesting_and_broken_references(tmp_path: Path) -> None:
    deep = {
        "kind": "and",
        "items": [
            {
                "kind": "or",
                "items": [
                    {"kind": "course", "code": "ASCI 2110"},
                    {
                        "kind": "and",
                        "items": [
                            {"kind": "course", "code": "ANPS 1190"},
                            {"kind": "course", "code": "ANPS 1200"},
                        ],
                    },
                ],
            },
            {
                "kind": "or",
                "items": [
                    {"kind": "course", "code": "BCOR 1400"},
                    {"kind": "course", "code": "BIOL 1400"},
                ],
            },
        ],
    }
    broken = course("BAD 1000", {"kind": "and", "items": [{"kind": "course", "code": "CS 1210"}]})
    broken["nodes"][0]["children"] = ["n9"]  # dangling reference
    answers = {"ASCI 2120": course("ASCI 2120", deep), "BAD 1000": broken}
    gateway = LLMGateway(Stub(answers), "m", tmp_path / "c", CacheMode.LIVE)
    trees, review, _ = parse_prereqs({"ASCI 2120": "deep", "BAD 1000": "broken"}, gateway)
    inner = trees["ASCI 2120"].items[0].items[1]
    assert isinstance(inner, AllPrereq) and inner.items[1] == CoursePrereq(
        kind="course", code="ANPS 1200"
    )
    assert "BAD 1000" not in trees and review[0]["code"] == "BAD 1000"


def test_known_answers_are_reused_and_only_new_notes_cost_a_call(tmp_path: Path) -> None:
    node = {"kind": "course", "code": "CS 2100", "min_grade": None, "concurrent_ok": False}
    known = {"Prerequisite: CS 2100": course("CS 2240", node)}
    stub = Stub({"CS 3200": course("CS 3200", {"kind": "course", "code": "CS 2240"})})
    gateway = LLMGateway(stub, "m", tmp_path / "c", CacheMode.LIVE)
    notes = {"CS 2240": "Prerequisite: CS 2100", "CS 3200": "Prerequisite: CS 2240"}
    trees, review, answers = parse_prereqs(notes, gateway, known=known)
    assert len(stub.requests) == 1 and "CS 2240 |" not in stub.requests[0].user  # only the new note
    assert set(trees) == {"CS 2240", "CS 3200"} and review == []
    assert set(answers) == {"Prerequisite: CS 2100", "Prerequisite: CS 2240"}  # store grows
