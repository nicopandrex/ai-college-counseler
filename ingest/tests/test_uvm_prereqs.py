import json
from pathlib import Path

from planner_ingest.uvm.prereqs import has_prereq_text, parse_prereqs, prereq_notes
from planner_llm import CacheMode, JsonRequest, LLMGateway
from planner_solver.domain import AllPrereq, AnyPrereq, CoursePrereq, StandingPrereq


class Stub:
    name = "stub"

    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers = answers
        self.requests: list[JsonRequest] = []

    def complete_json(self, request: JsonRequest, model: str) -> str:
        self.requests.append(request)
        codes = [line.split(" | ")[0] for line in request.user.splitlines() if " | " in line]
        return json.dumps({"courses": [self.answers[c] for c in codes]})


def course(code, node, ambiguous=False, note=None):
    return {"code": code, "prereq": node, "ambiguous": ambiguous, "note": note}


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
    trees, review = parse_prereqs(notes, gateway, batch_size=2)

    assert trees["CS 2240"] == CoursePrereq(kind="course", code="CS 2100", min_grade="C-")
    assert isinstance(trees["ALE 2010"], AnyPrereq) and isinstance(
        trees["ALE 2010"].items[0], AllPrereq
    )
    assert trees["ALE 1360"] == StandingPrereq(kind="standing", minimum="junior")
    assert {r["code"] for r in review} == {"ART 2000", "BAD 3000"}  # unparsed; malformed code
    assert all(r["notes"] for r in review)


def test_a_course_the_model_skips_is_queued_not_dropped(tmp_path: Path) -> None:
    class Skipper(Stub):
        def complete_json(self, request: JsonRequest, model: str) -> str:
            return json.dumps({"courses": []})

    gateway = LLMGateway(Skipper({}), "m", tmp_path / "c", CacheMode.LIVE)
    trees, review = parse_prereqs({"CS 3200": "Prerequisite: CS 2240"}, gateway)
    assert "CS 3200" not in trees
    assert review == [
        {"code": "CS 3200", "notes": "Prerequisite: CS 2240", "reason": "not returned by the model"}
    ]
