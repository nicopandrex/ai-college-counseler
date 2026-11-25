"""The chat loop, with a stub translator (no LLM) on the synthetic term."""

import json
from dataclasses import replace
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
    assert set(chat.view()["conflict_ids"]) == {"c1", "c2", "c3"}
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
    assert reply.startswith("You have 6 requirements left:")
    assert "  • Macroeconomics" in reply and "Schedule" not in reply and chat.spec is None
    assert chat.view()["suggestions"][-1] == {
        "label": "Plan next semester",
        "message": "Plan my next semester",
    }


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
    assert "B TR 11:30am–12:45pm (Ana Diaz)" in reply
    assert "It counts toward Macroeconomics." in reply


def test_instructor_opinions_are_declined_honestly(tmp_path: Path) -> None:
    provider = Script(answer(intent="question", question_topic="instructor_opinion"))
    assert "don't have reviews" in session(provider, tmp_path).handle("is Diaz good?")


def test_plan_mode_is_never_sent_to_the_term_solver(tmp_path: Path) -> None:
    plan = answer(con("c1", "target_graduation_term", term="2028SP"))
    plan["mode"], plan["target_term"] = "plan", None
    chat = session(Script(plan), tmp_path)
    reply = chat.handle("can I graduate by spring 2028?")
    assert reply.startswith("I can only plan one semester (Spring 2027) for now")
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


def test_view_carries_the_rules_and_schedules_the_text_describes(tmp_path: Path) -> None:
    chat = session(
        Script(answer(con("c1", "include_course", src="macro", course="ECON 2020"))), tmp_path
    )
    chat.handle("macro")
    view = chat.view()
    assert view["rules"][0] == {
        "id": "c1",
        "text": "take ECON 2020 (Macroeconomics)",
        "must": True,
        "said": "macro",
        "default": False,
        "removable": True,
    }
    assert view["status"] == "ok" and 1 <= len(view["schedules"]) <= 3
    econ = next(s for s in view["schedules"][0]["sections"] if s["course"] == "ECON 2020")
    assert econ["meetings"] and econ["counts_toward"] == ["Macroeconomics"]
    assert view["requirements"][0]["title"] and view["why"] == []
    json.dumps(view)  # JSON-safe for the API


def test_closing_a_chip_drops_it_without_the_llm(tmp_path: Path) -> None:
    provider = Script(
        answer(
            con("c1", "include_course", src="macro", course="ECON 2020"),
            con("c2", "free_day", src="Fridays off", day="F"),
        )
    )
    chat = session(provider, tmp_path)
    chat.handle("macro, Fridays off")
    reply = chat.drop("c2")
    assert reply.startswith("Dropped “Fridays free”.") and len(provider.requests) == 1
    assert [r["id"] for r in chat.view()["rules"] if not r["default"]] == ["c1"]
    assert chat.drop("c2") == "That request isn't active any more."


def test_a_closed_default_stays_closed_on_the_next_turn(tmp_path: Path) -> None:
    provider = Script(
        answer(con("c1", "include_course", src="macro", course="ECON 2020")),
        answer(
            con("c1", "include_course", src="macro", course="ECON 2020"),
            con("c2", "free_day", src="Fridays off", day="F"),
        ),
    )
    chat = session(provider, tmp_path)
    chat.validation = replace(chat.validation, preferred_credit_range=(3, 4))
    chat.handle("macro")
    chat.drop("default_load_preference")
    chat.handle("and Fridays off")
    assert "default_load_preference" not in {r["id"] for r in chat.view()["rules"]}


def test_the_full_time_band_can_be_changed_but_not_closed(tmp_path: Path) -> None:
    chat = session(
        Script(answer(con("c1", "include_course", src="macro", course="ECON 2020"))), tmp_path
    )
    chat.handle("macro")
    assert "can't be removed" in chat.drop("default_credits")
    rules = {r["id"]: r for r in chat.view()["rules"]}
    assert not rules["default_credits"]["removable"] and rules["c1"]["removable"]


def test_closing_your_own_credit_load_brings_back_the_full_time_band(tmp_path: Path) -> None:
    load = con("c1", "credit_range", src="just 3 credits", min=3, max=3)
    chat = session(Script(answer(load)), tmp_path)
    chat.handle("just 3 credits")
    assert "default_credits" not in {r["id"] for r in chat.view()["rules"]}
    chat.drop("c1")
    view = chat.view()
    assert "default_credits" in {r["id"] for r in view["rules"]}
    assert view["schedules"] and all(s["credits"] <= 7 for s in view["schedules"])  # not unbounded


def test_questions_are_in_the_view_for_tap_to_answer(tmp_path: Path) -> None:
    question = {
        "question": "How early is too early?",
        "kind": "ambiguity",
        "constraint_id": "c1",
        "options": ["9:00", "10:00"],
        "blocking": False,
    }
    early = con("c1", "no_earlier_than", "soft", 3, src="no early mornings", time="10:00")
    chat = session(Script(answer(early, clarifications=[question])), tmp_path)
    chat.handle("no early mornings")
    assert chat.view()["questions"] == [
        {"question": "How early is too early?", "options": ["9:00", "10:00"]}
    ]


def test_catalog_search_matches_code_title_or_instructor_from_the_term_data(
    tmp_path: Path,
) -> None:
    chat = session(Script(), tmp_path)
    found = chat.catalog("econ2020")
    assert found["total"] == 1
    macro = found["courses"][0]
    assert (macro["code"], macro["title"], macro["status"]) == (
        "ECON 2020",
        "Macroeconomics",
        "open",
    )
    assert macro["counts_toward"] == ["Macroeconomics"]
    assert macro["sections"][1] == {
        "id": "ECON 2020 B",
        "component": "LEC",
        "when": "TR 11:30am–12:45pm",
        "instructors": ["Ana Diaz"],
        "online": False,
        "seats_open": 4,
    }
    assert [c["code"] for c in chat.catalog("kim lee")["courses"]] == ["CS 3200", "CS 3410"]
    assert [c["code"] for c in chat.catalog("software")["courses"]] == ["CS 3200"]


def test_catalog_marks_taken_and_blocked_courses_and_defaults_to_what_counts(
    tmp_path: Path,
) -> None:
    chat = session(Script(), tmp_path)
    taken = chat.catalog("CS 1210")["courses"][0]
    assert taken["status"] == "taken" and taken["notes"] == []
    blocked = chat.catalog("capstone")["courses"][0]
    assert blocked["status"] == "blocked" and blocked["notes"] == ["requires CS 3999"]
    default = [c["code"] for c in chat.catalog("")["courses"]]
    assert "ART 1100" not in default and "ECON 2020" in default  # counts for nothing: hidden
    assert chat.catalog("zzz") == {"courses": [], "total": 0}


def test_each_plan_says_which_requests_it_meets_and_what_it_adds_per_requirement(
    tmp_path: Path,
) -> None:
    late = con("c2", "no_earlier_than", "soft", 3, src="nothing before 1", time="13:00")
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    chat = session(Script(answer(macro, late)), tmp_path)
    chat.handle("macro, and nothing before 1 if I can")
    view = chat.view()
    plan = view["schedules"][0]
    assert "c2" in plan["missed_rules"] and "c1" not in plan["missed_rules"]  # macro is 11:30
    assert view["conflict_ids"] == []
    assert {
        "title": "Macroeconomics",
        "needed": None,
        "unit": None,
        "planned": 1,
        "courses": ["ECON 2020"],
    } in plan["progress"]
    assert len(plan["progress"]) == len(view["requirements"])  # every open requirement


def test_adding_a_course_to_a_plan_offers_to_add_it_or_rebuild(tmp_path: Path) -> None:
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    light = con("c2", "credit_range", "soft", 5, src="ideally 3 credits", min=3, max=3)
    nets = con("c3", "include_course", src="add networks", course="CS 3410")
    provider = Script(answer(macro, light), answer(macro, light, nets))
    chat = session(provider, tmp_path)
    chat.handle("macro, ideally 3 credits")
    before = chat.view()["schedules"][0]
    assert [s["course"] for s in before["sections"]] == ["ECON 2020"]

    reply = chat.handle("add networks")
    choices = [c["text"] for c in chat.view()["choices"]]
    assert choices[0].startswith("Add CS 3410 (Networks) to Plan A → 6 credits")
    assert "misses" in choices[0]  # the "ideally 3 credits" preference
    assert choices[-1] == "Rebuild every plan around it"
    assert "1. " + choices[0] in reply
    assert chat.view()["schedules"][0] == before  # nothing changes until they pick

    reply = chat.handle("1")
    assert len(provider.requests) == 2  # picking is deterministic, no LLM
    plan = chat.view()["schedules"][0]
    econ = next(s for s in plan["sections"] if s["course"] == "ECON 2020")
    assert econ in before["sections"]  # the class already planned keeps its section
    assert {s["course"] for s in plan["sections"]} == {"ECON 2020", "CS 3410"}
    assert chat.view()["choices"] == [] and "c3" in {r["id"] for r in chat.view()["rules"]}


def test_a_full_plan_offers_swaps_that_keep_the_requested_courses(tmp_path: Path) -> None:
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    load = con("c2", "credit_range", src="6 credits", min=6, max=6)
    provider = Script(answer(macro, load))
    chat = session(provider, tmp_path)
    chat.handle("macro, 6 credits")
    planned = {s["course"] for s in chat.view()["schedules"][0]["sections"]}
    other = next(iter(planned - {"ECON 2020"}))
    adding = next(c for c in ("CS 3410", "HIST 1010", "SOC 1000") if c not in planned)
    provider.answers.append(answer(macro, load, con("c3", "include_course", course=adding)))
    chat.handle(f"add {adding}")
    choices = [c["text"] for c in chat.view()["choices"]]
    assert not any(c.startswith("Add ") for c in choices)  # no room: 6 credits is a must
    assert any(c.startswith(f"Swap out {other}") for c in choices)
    assert not any("Swap out ECON 2020" in c for c in choices)  # they asked for macro
    swap = 1 + next(i for i, c in enumerate(choices) if c.startswith(f"Swap out {other}"))
    chat.handle(str(swap))
    courses = {s["course"] for s in chat.view()["schedules"][0]["sections"]}
    assert courses == {"ECON 2020", adding}


def test_asking_for_a_course_already_planned_keeps_the_plan(tmp_path: Path) -> None:
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    provider = Script(answer(macro))
    chat = session(provider, tmp_path)
    chat.handle("macro")
    plan = chat.view()["schedules"][0]
    there = next(s["course"] for s in plan["sections"] if s["course"] != "ECON 2020")
    provider.answers.append(answer(macro, con("c2", "include_course", course=there)))
    assert chat.handle(f"I want {there}").endswith(
        f"{there} is already in Plan A, so I kept it as it is."
    )
    assert chat.view()["schedules"][0]["sections"] == plan["sections"]


def test_rebuild_solves_from_scratch_with_the_new_course(tmp_path: Path) -> None:
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    nets = con("c3", "include_course", src="add networks", course="CS 3410")
    chat = session(Script(answer(macro), answer(macro, nets)), tmp_path)
    chat.handle("macro")
    chat.handle("add networks")
    rebuild = len(chat.view()["choices"])
    reply = chat.handle(str(rebuild))
    assert "Found" in reply or "Schedule 1" in reply
    for plan in chat.view()["schedules"]:
        assert {"ECON 2020", "CS 3410"} <= {s["course"] for s in plan["sections"]}


def test_the_translator_sees_the_recent_conversation(tmp_path: Path) -> None:
    provider = Script(
        answer(intent="question", question_topic="remaining_requirements"),
        answer(
            intent="question", question_topic="requirement_details", question_requirements=["MACRO"]
        ),
    )
    chat = session(provider, tmp_path)
    first = chat.handle("what do I still need?")
    reply = chat.handle("how many credits is the macro one?")
    prompt = provider.requests[1].user
    assert "RECENT CONVERSATION:" in prompt and "student: what do I still need?" in prompt
    assert f"planner: {first[:60]}" in prompt
    assert reply.startswith("Macroeconomics: ") and "ECON 2020" in reply


def test_course_options_are_answered_from_prerequisites(tmp_path: Path) -> None:
    provider = Script(
        answer(
            intent="question",
            question_topic="course_options",
            question_subjects=["CS"],
            question_courses=[],
        )
    )
    reply = session(provider, tmp_path).handle("what CS classes can I take?")
    assert reply.startswith("3 CS courses you haven't taken are offered in Spring 2027.")
    assert "CS 4999" in reply and "requires CS 3999" in reply  # its prerequisite isn't met


def test_undo_brings_back_the_requests_and_plans_before_a_change(tmp_path: Path) -> None:
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    fridays = con("c2", "free_day", src="Fridays off", day="F")
    chat = session(Script(answer(macro), answer(macro, fridays)), tmp_path)
    chat.handle("macro")
    before = chat.view()
    chat.handle("and Fridays off")
    assert chat.view()["suggestions"] == [{"label": "Undo", "message": "/undo"}]
    assert chat.handle("/undo").startswith("Undone")
    assert (
        chat.view()["rules"] == before["rules"] and chat.view()["schedules"] == before["schedules"]
    )
    assert chat.handle("/undo") == "There's nothing to undo."


def test_the_web_hears_what_changed_and_the_load_assumption_once(tmp_path: Path) -> None:
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    fridays = con("c2", "free_day", src="Fridays off", day="F")
    chat = session(Script(answer(macro), answer(macro, fridays)), tmp_path)
    chat.list_schedules = False
    first = chat.handle("macro")
    assert first.startswith("Got it: added “take ECON 2020 (Macroeconomics)”.")
    assert "I'm planning a full-time load (3–7 credits)" in first
    second = chat.handle("and Fridays off")
    assert second.startswith("Got it: added “Fridays free”.") and "full-time load" not in second


def test_a_note_about_the_audit_is_said_once(tmp_path: Path) -> None:
    from planner_solver.domain import RequirementTarget

    odd = RequirementTarget(title="Macroeconomic Theory", selectors=("ECON 2020 with grade = B",))
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    fridays = con("c2", "free_day", src="Fridays off", day="F")
    chat = session(Script(answer(macro), answer(macro, fridays)), tmp_path)
    chat.student = chat.student.model_copy(
        update={"open_requirements": {**chat.student.open_requirements, "THEORY": odd}}
    )
    assert "“Macroeconomic Theory” rule" in chat.handle("macro")
    assert "Macroeconomic Theory" not in chat.handle("and Fridays off")


def test_a_long_first_request_is_counted_not_repeated(tmp_path: Path) -> None:
    many = [
        con("c1", "include_course", src="macro", course="ECON 2020"),
        con("c2", "free_day", src="Fridays off", day="F"),
        con("c3", "include_course", src="networks", course="CS 3410"),
        con("c4", "no_later_than", src="done by 5", time="17:00"),
    ]
    chat = session(Script(answer(*many)), tmp_path)
    chat.list_schedules = False
    reply = chat.handle("macro, networks, Fridays off, done by 5")
    assert reply.startswith("Got it: added 4 requests (listed above the calendar).")


def test_replies_are_reworded_and_the_wording_is_what_the_chat_remembers(tmp_path: Path) -> None:
    from planner_chat.phrasing import Phraser

    class Friendly:
        name = "friendly"

        def complete_json(self, request: JsonRequest, model: str) -> str:
            return json.dumps({"reply": "Hey! What would you like for Spring 2027?"})

    chat = session(Script(answer(intent="greeting")), tmp_path)
    friendly = "Hey! What would you like for Spring 2027?"
    chat.phraser = Phraser(LLMGateway(Friendly(), "m", tmp_path / "p", CacheMode.LIVE))
    assert chat.handle("hi") == friendly
    assert chat.history[-1] == ("planner", friendly)
    assert chat.handle("/undo") == "There's nothing to undo."  # commands aren't reworded


def test_plan_questions_use_the_plan_on_screen_or_the_ones_named(tmp_path: Path) -> None:
    macro = con("c1", "include_course", src="macro", course="ECON 2020")
    provider = Script(
        answer(macro),
        answer(intent="question", question_topic="plan_progress", question_plans=[]),
        answer(intent="question", question_topic="plan_progress", question_plans=["A", "b"]),
    )
    chat = session(provider, tmp_path)
    chat.handle("macro")
    assert len(chat.view()["schedules"]) >= 2
    reply = chat.handle("if I do this plan how many requirements are left?", plan=1)
    assert reply.startswith("With Plan B (") and "of your 6 open requirements" in reply
    prompt = provider.requests[1].user
    assert "CURRENT PLANS:\n- Plan A: " in prompt and "(on screen)" in prompt.split("- Plan B")[1]
    compared = chat.handle("compare plan A and B").splitlines()
    assert compared[0].startswith("Plan A (") and compared[1].startswith("Plan B (")


def test_a_plan_question_before_any_plan_says_so(tmp_path: Path) -> None:
    chat = session(Script(answer(intent="question", question_topic="plan_progress")), tmp_path)
    assert chat.handle("what does plan A leave?").startswith("There's no plan yet.")
