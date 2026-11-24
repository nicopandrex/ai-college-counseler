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
    *constraints: dict[str, Any],
    restatement: str = "ok",
    oos: list | None = None,
    clarifications: list | None = None,
    **intent: Any,
) -> dict[str, Any]:
    return {
        **intent,
        "spec_version": "0.1",
        "mode": "term",
        "target_term": "2027SP",
        "restatement": restatement,
        "constraints": list(constraints),
        "clarifications": clarifications or [],
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


def test_a_request_becomes_schedules_with_a_templated_summary(tmp_path: Path) -> None:
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
    assert reply.startswith(
        "Working with: take ECON 2020 (Macroeconomics); a full-time load (3–7 credits)"
    )
    assert "Macro, any time." not in reply  # the LLM's own wording is never shown
    assert "Schedule 1" in reply and "ECON 2020" in reply


def test_already_taken_course_is_left_out_and_the_rest_is_solved(tmp_path: Path) -> None:
    provider = Script(
        answer(
            con("c1", "include_course", src="programming one", course="CS 1210"),
            con("c2", "include_course", src="macro", course="ECON 2020"),
        )
    )
    reply = session(provider, tmp_path).handle("programming one and macro")
    assert "Left out “programming one”: CS 1210 is already taken or registered." in reply
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
    assert reply.startswith("Dropped “only sections with open seats”.") and "Schedule 1" in reply
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
    assert "I can't do “same as my roommate” yet." in reply
    logged = [json.loads(line) for line in (tmp_path / "oos.jsonl").read_text().splitlines()]
    assert logged[0]["request"] == "same schedule as a friend"


def test_spec_command_lists_the_active_requests(tmp_path: Path) -> None:
    chat = session(
        Script(answer(con("c1", "free_day", "soft", 2, src="Fridays off", day="F"))), tmp_path
    )
    chat.handle("Fridays off would be nice")
    listing = chat.handle("/spec")
    assert "Fridays free · preference, weight 2" in listing


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
    assert reply.startswith(
        "Dropped “take ECON 2020 (Macroeconomics)” "
        "(and “not with Ana Diaz for ECON 2020”, which only applied to it)."
    )
    assert {c["id"] for c in chat.spec["constraints"]} >= {"c3", "c4"}
    assert not {"c1", "c2"} & {c["id"] for c in chat.spec["constraints"]}


def test_greetings_and_thanks_neither_solve_nor_change_the_request(tmp_path: Path) -> None:
    provider = Script(
        answer(con("c1", "free_day", src="Fridays off", day="F")),
        answer(intent="thanks"),
        answer(intent="greeting"),
    )
    chat = session(provider, tmp_path)
    chat.handle("Fridays off")
    before = chat.spec
    assert chat.handle("thanks!") == "You're welcome! Tell me if you want to change anything."
    assert "Schedule" not in chat.handle("hi") and chat.spec == before


def test_what_do_i_still_need_is_answered_from_the_audit(tmp_path: Path) -> None:
    chat = session(
        Script(answer(intent="question", question_topic="remaining_requirements")), tmp_path
    )
    reply = chat.handle("what do I still need?")
    assert reply.startswith("From your audit, you still need:")
    assert "  • Macroeconomics" in reply and "Schedule" not in reply and chat.spec is None


def test_credits_question_quotes_the_audit(tmp_path: Path) -> None:
    from planner_chat.session import StudentFacts

    chat = session(Script(answer(intent="question", question_topic="credits_earned")), tmp_path)
    chat.facts = StudentFacts(credits_earned=87, credits_in_progress=16, standing="Junior")
    assert chat.handle("how many credits do I have?") == (
        "Your audit shows 87 credits earned, plus 16 in progress. Class standing: Junior."
    )


def test_course_questions_list_sections_from_the_catalog(tmp_path: Path) -> None:
    provider = Script(
        answer(intent="question", question_topic="course_info", question_courses=["ECON 2020"])
    )
    reply = session(provider, tmp_path).handle("when is macro?")
    assert "ECON 2020 B  TR 11:30am–12:45pm  · Ana Diaz" in reply
    assert "Counts toward: Macroeconomics" in reply


def test_instructor_opinions_are_declined_honestly(tmp_path: Path) -> None:
    provider = Script(answer(intent="question", question_topic="instructor_opinion"))
    assert "don't have reviews" in session(provider, tmp_path).handle("is Diaz good?")


def test_plan_mode_is_never_sent_to_the_term_solver(tmp_path: Path) -> None:
    plan = answer(con("c1", "target_graduation_term", term="2028SP"))
    plan["mode"], plan["target_term"] = "plan", None
    chat = session(Script(plan), tmp_path)
    reply = chat.handle("can I graduate by spring 2028?")
    assert reply.startswith("I can only plan one semester (2027SP) for now")
    assert "Schedule" not in reply and chat.spec is None


def test_out_of_scope_and_questions_are_said_once_not_carried(tmp_path: Path) -> None:
    question = {
        "question": "How early is too early?",
        "kind": "ambiguity",
        "constraint_id": "c1",
        "options": ["9:00", "10:00"],
        "blocking": False,
    }
    early = con("c1", "no_earlier_than", "soft", 3, src="no early mornings", time="10:00")
    provider = Script(
        answer(
            early, oos=[{"request": "x", "user_text": "like my friend"}], clarifications=[question]
        ),
        answer(early, con("c2", "free_day", src="Fridays off", day="F"), clarifications=[question]),
    )
    chat = session(provider, tmp_path)
    first = chat.handle("no early mornings, like my friend")
    second = chat.handle("and Fridays off")
    assert "How early is too early?" in first and "How early is too early?" not in second
    assert "like my friend" in first and "like my friend" not in second
    prior = provider.requests[1].user.split("PRIOR SPEC:")[1]
    assert '"out_of_scope": []' in prior and "default_credits" not in prior


def test_unreadable_params_get_a_plain_message(tmp_path: Path) -> None:
    provider = Script(answer(con("c1", "free_day", src="weekends off", day="weekend")))
    reply = session(provider, tmp_path).handle("weekends off")
    assert "Left out “weekends off”: I couldn't turn it into a rule." in reply
    assert "pydantic" not in reply and "validation error" not in reply


def test_what_if_i_fail_reruns_with_that_assumption_without_changing_the_plan(
    tmp_path: Path,
) -> None:
    from planner_chat.session import StudentFacts

    provider = Script(
        answer(con("c1", "include_course", src="macro", course="ECON 2020")),
        answer(intent="question", question_topic="what_if_fail", question_courses=["CS 1210"]),
    )
    chat = session(provider, tmp_path)
    chat.facts = StudentFacts(in_progress=("CS 1210",))
    asked: list[tuple[str, ...]] = []

    def failing(codes: tuple[str, ...]):
        asked.append(codes)
        student = chat.student.model_copy(
            update={"unplannable_courses": frozenset(), "counted_courses": frozenset()}
        )
        return student, chat.validation

    chat.what_if = failing
    chat.handle("macro")
    before = chat.spec
    reply = chat.handle("what if I fail programming one?")
    assert asked == [("CS 1210",)] and chat.spec == before
    assert reply.startswith("If you don't pass CS 1210, here's 2027SP with the same requests")
    assert "Schedule 1" in reply
