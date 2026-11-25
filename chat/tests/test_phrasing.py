"""The rewording step: natural replies, shown only when they keep the draft's facts."""

import json
from pathlib import Path

from planner_chat.phrasing import Phraser, instructor_names, ungrounded
from planner_llm import CacheMode, JsonRequest, LLMError, LLMGateway

DRAFT = (
    "ECON 1450 Principles of Microeconomics is 3 credits. Spring 2027 has 2 sections: "
    "A MWF 1:10–2:00pm (S. Smith) and B MW 3:30–4:45pm (C. Vizcarra). It's a prerequisite "
    "for 5 courses this term: ECON 2400, ECON 2450, ECON 2700 and 2 more."
)
GOOD = (
    "ECON 1450 (Principles of Microeconomics) is 3 credits, with 2 sections in Spring 2027: "
    "MWF 1:10–2:00pm with S. Smith, or MW 3:30–4:45pm with C. Vizcarra. It unlocks 5 courses, "
    "including ECON 2400, ECON 2450 and ECON 2700. Want me to add it?"
)
NAMES = frozenset({"Smith", "Vizcarra", "Esselstrom"})


def test_a_faithful_rewording_passes() -> None:
    assert ungrounded(DRAFT, GOOD, NAMES) == []


def test_any_invented_changed_or_dropped_fact_is_caught() -> None:
    assert ungrounded(DRAFT, GOOD.replace("ECON 2700", "ECON 2990"), NAMES)  # new course
    assert ungrounded(DRAFT, GOOD.replace(", ECON 2450", ""), NAMES)  # dropped course
    assert ungrounded(DRAFT, GOOD.replace("3 credits", "4 credits"), NAMES)
    assert ungrounded(DRAFT, GOOD.replace("5 courses", "six courses"), NAMES)  # number word
    assert ungrounded(DRAFT, GOOD.replace("3:30", "3:45"), NAMES)
    assert ungrounded(DRAFT, GOOD.replace("C. Vizcarra", "E. Esselstrom"), NAMES)
    # a number the draft has elsewhere still can't move to a different amount
    assert ungrounded(DRAFT, GOOD.replace("5 courses", "2 courses"), NAMES)


def test_number_words_that_match_the_draft_are_fine() -> None:
    assert ungrounded(DRAFT, GOOD.replace("2 sections", "two sections"), NAMES) == []


def test_a_bare_number_may_gain_its_unit_but_a_stated_amount_must_stay() -> None:
    draft = "Alongside ECON 1450, you can take 4: ECON 1130 and 3 more. ECON 1130 is 3 credits."
    ok = "With ECON 1450 you can take 4 courses, like ECON 1130 (3-credit) and 3 more."
    assert ungrounded(draft, ok) == []
    assert ungrounded(draft, ok.replace("(3-credit)", "(4-credit)"))  # amount changed
    assert ungrounded("ECON 1130 is 3 credits.", "ECON 1130 is a 3-credit course.") == []


def test_instructor_surnames_come_from_every_name_format() -> None:
    assert instructor_names(["S. Smith", "Smith, John A", "Ana Diaz", "Staff", "Li"]) == {
        "Smith",
        "Diaz",
        "Staff",
    }


class Canned:
    name = "canned"

    def __init__(self, *replies: str | Exception) -> None:
        self.replies, self.requests = list(replies), []

    def complete_json(self, request: JsonRequest, model: str) -> str:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return json.dumps({"reply": reply})


def phraser(tmp_path: Path, *replies: str | Exception) -> Phraser:
    gateway = LLMGateway(Canned(*replies), "m", tmp_path, CacheMode.LIVE)
    return Phraser(gateway, NAMES)


def test_the_rewording_is_shown_when_it_keeps_the_facts(tmp_path: Path) -> None:
    p = phraser(tmp_path, GOOD)
    assert p.reword(DRAFT, "tell me about micro") == GOOD and p.fallbacks == 0
    sent = p.gateway.provider.requests[0]  # type: ignore[attr-defined]
    assert "MESSAGE:\ntell me about micro" in sent.user and DRAFT in sent.user


def test_the_draft_is_shown_when_the_rewording_strays_or_fails(tmp_path: Path) -> None:
    p = phraser(tmp_path, GOOD.replace("3 credits", "4 credits"), LLMError("down"), "")
    assert p.reword(DRAFT, "a") == DRAFT
    assert p.reword(DRAFT, "b") == DRAFT
    assert p.reword(DRAFT, "c") == DRAFT and p.fallbacks == 3
