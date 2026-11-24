"""The chat loop, with a stub translator (no LLM) on the synthetic term."""

import json
from pathlib import Path
from typing import Any

from term_fixtures import STUDENT, TERM

from planner_chat.session import ChatSession
from planner_chat.translator import TranslatorContext
from planner_llm import CacheMode, JsonRequest, LLMGateway
from planner_solver.validation import ValidationContext


def con(
    cid: str, ctype: str, enf: str = "hard", w: int = 5, src: str = "", **params: Any
) -> dict[str, Any]:
    return {
        "id": cid,
        "type": ctype,
        "params_json": json.dumps(params),
        "enforcement": enf,
        "weight": w,
        "weight_source": "stated",
        "confidence": 0.9,
        "source_text": src,
        "data_dependency": "reliable",
    }


def answer(
    *constraints: dict[str, Any], restatement: str = "ok", oos: list | None = None
) -> dict[str, Any]:
    return {
        "spec_version": "0.1",
        "mode": "term",
        "target_term": "2027SP",
        "restatement": restatement,
        "constraints": list(constraints),
        "clarifications": [],
        "out_of_scope": oos or [],
    }


class Script:
    """Stub translator provider: one canned answer per call."""

    name = "script"

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.requests: list[JsonRequest] = []

    def complete_json(self, request: JsonRequest, model: str) -> str:
        self.requests.append(request)
        return json.dumps(self.answers[len(self.requests) - 1])


def session(provider: Script, tmp_path: Path) -> ChatSession:
    return ChatSession(
        context=TranslatorContext(
            target_term="2027SP",
            open_requirements=[("MACRO", "Macroeconomics")],
            catalog=[(c.code, c.title) for c in TERM.courses.values()],
        ),
        term=TERM,
        student=STUDENT,
        validation=ValidationContext(
            course_codes=frozenset(TERM.courses),
            requirement_ids=frozenset(STUDENT.open_requirements),
            unplannable_courses=STUDENT.unplannable_courses,
            default_credit_range=(3, 7),
        ),
        gateway=LLMGateway(provider, "m", tmp_path / "cache", CacheMode.LIVE),
        out_of_scope_log=tmp_path / "oos.jsonl",
    )


def test_a_request_becomes_schedules_with_the_restatement(tmp_path: Path) -> None:
    chat = session(
        Script(
            answer(
                con("c1", "include_course", src="macro", course="ECON 2020"),
                restatement="Macro, any time.",
            )
        ),
        tmp_path,
    )
    reply = chat.handle("I want macro")
    assert reply.startswith("Got it: Macro, any time.")
    assert "Schedule 1" in reply and "ECON 2020" in reply


def test_already_taken_course_is_left_out_and_the_rest_is_solved(tmp_path: Path) -> None:
    provider = Script(
        answer(
            con("c1", "include_course", src="programming one", course="CS 1210"),
            con("c2", "include_course", src="macro", course="ECON 2020"),
        )
    )
    reply = session(provider, tmp_path).handle("programming one and macro")
    assert (
        "Left out “programming one”: CS 1210 is already completed, in progress or registered"
        in reply
    )
    assert "ECON 2020" in reply and "Schedule 1" in reply


def test_infeasible_offers_numbered_fixes_and_a_number_applies_one_without_the_llm(
    tmp_path: Path,
) -> None:
    provider = Script(
        answer(
            con("c1", "include_course", src="macro", course="ECON 2020"),
            con(
                "c2",
                "instructor_preference",
                w=4,
                src="not with Diaz",
                name="Ana Diaz",
                polarity="exclude",
                course="ECON 2020",
            ),
            con("c3", "open_seats_only", w=2, src="only open seats", value=True),
        )
    )
    chat = session(provider, tmp_path)
    reply = chat.handle("macro, not Diaz, open seats only")
    assert "can't all hold at once" in reply and "Reply with a fix's number" in reply
    reply = chat.handle("1")  # least important first: drop "only open seats"
    assert len(provider.requests) == 1  # no second LLM call
    assert reply.startswith("Dropped “only open seats”.") and "Schedule 1" in reply
    assert [c["id"] for c in chat.spec["constraints"] if c["id"] != "default_credits"] == [
        "c1",
        "c2",
    ]


def test_follow_ups_send_the_current_spec_as_prior(tmp_path: Path) -> None:
    provider = Script(
        answer(con("c1", "include_course", src="macro", course="ECON 2020")),
        answer(
            con("c1", "include_course", src="macro", course="ECON 2020"),
            con("c2", "free_day", src="Fridays off", day="F"),
        ),
    )
    chat = session(provider, tmp_path)
    chat.handle("macro")
    chat.handle("and keep Fridays free")
    assert "PRIOR SPEC:" in provider.requests[1].user and '"ECON 2020"' in provider.requests[1].user


def test_out_of_scope_is_said_honestly_and_logged(tmp_path: Path) -> None:
    provider = Script(
        answer(oos=[{"request": "same schedule as a friend", "user_text": "same as my roommate"}])
    )
    reply = session(provider, tmp_path).handle("same as my roommate")
    assert "can't do that yet: same schedule as a friend" in reply
    logged = [json.loads(line) for line in (tmp_path / "oos.jsonl").read_text().splitlines()]
    assert logged[0]["request"] == "same schedule as a friend"


def test_spec_command_lists_the_active_requests(tmp_path: Path) -> None:
    chat = session(
        Script(answer(con("c1", "free_day", "soft", 2, src="Fridays off", day="F"))), tmp_path
    )
    chat.handle("Fridays off would be nice")
    listing = chat.handle("/spec")
    assert "“Fridays off” — free_day (day F) · soft, weight 2" in listing


def test_dropping_a_course_also_drops_rules_scoped_to_it(tmp_path: Path) -> None:
    provider = Script(
        answer(
            con("c1", "include_course", src="macro", course="ECON 2020"),
            con(
                "c2",
                "instructor_preference",
                w=4,
                src="not with Diaz",
                name="Ana Diaz",
                polarity="exclude",
                course="ECON 2020",
            ),
            con("c3", "free_day", w=5, src="Fridays off", day="F"),
            con("c4", "no_earlier_than", w=5, src="nothing before 11", time="11:00"),
        )
    )
    chat = session(provider, tmp_path)
    reply = chat.handle("macro not with Diaz, Fridays off, nothing before 11")
    assert "can't all hold at once" in reply
    fix = next(n for n, r in enumerate(chat._result.relaxations, 1) if r.constraint_id == "c1")
    reply = chat.handle(str(fix))
    assert reply.startswith("Dropped “macro” (and “not with Diaz”, which only applied to it).")
    assert {c["id"] for c in chat.spec["constraints"]} >= {"c3", "c4"}
    assert not {"c1", "c2"} & {c["id"] for c in chat.spec["constraints"]}
