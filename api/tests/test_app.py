"""Web API over the synthetic term, with a scripted translator (no LLM, no real audit)."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from term_fixtures import STUDENT, TERM

from planner_api.app import create_app
from planner_chat.session import ChatSession, StudentFacts
from planner_chat.translator import TranslatorContext
from planner_llm import CacheMode, JsonRequest, LLMGateway
from planner_solver.validation import ValidationContext

PDF = b"%PDF-1.4 synthetic"


def answer(*constraints: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": "schedule",
        "question_topic": None,
        "question_courses": [],
        "spec_version": "0.1",
        "mode": "term",
        "target_term": "2027SP",
        "restatement": "ok",
        "constraints": list(constraints),
        "clarifications": [],
        "out_of_scope": [],
    }


def con(cid: str, ctype: str, src: str, **params: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "type": ctype,
        "params_json": json.dumps(params),
        "enforcement": "hard",
        "weight": 5,
        "weight_source": "stated",
        "confidence": 0.9,
        "source_text": src,
        "data_dependency": "reliable",
    }


class Script:
    name = "script"

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers, self.calls = list(answers), 0

    def complete_json(self, request: JsonRequest, model: str) -> str:
        self.calls += 1
        return json.dumps(self.answers[self.calls - 1])


def client(tmp_path: Path, provider: Script) -> tuple[TestClient, list[bytes]]:
    seen: list[bytes] = []

    def opener(pdf: Path) -> ChatSession:
        seen.append(pdf.read_bytes())
        return ChatSession(
            TranslatorContext("2027SP", [("MACRO", "Macroeconomics")], []),
            TERM,
            STUDENT,
            ValidationContext(
                course_codes=frozenset(TERM.courses),
                requirement_ids=frozenset(STUDENT.open_requirements),
                unplannable_courses=STUDENT.unplannable_courses,
                default_credit_range=(3, 7),
            ),
            LLMGateway(provider, "m", tmp_path, CacheMode.LIVE),
            facts=StudentFacts(credits_earned=80, credits_in_progress=15),
        )

    return TestClient(create_app(opener)), seen


def test_upload_then_chat_then_close_a_chip(tmp_path: Path) -> None:
    provider = Script(
        answer(
            con("c1", "include_course", "macro", course="ECON 2020"),
            con("c2", "free_day", "Fridays off", day="F"),
        )
    )
    api, seen = client(tmp_path, provider)
    started = api.post("/api/sessions", content=PDF, headers={"content-type": "application/pdf"})
    assert started.status_code == 200 and seen == [PDF]
    body = started.json()
    assert body["reply"].startswith("I read your audit: 80 credits earned plus 15 in progress")
    sid = body["id"]

    turn = api.post(f"/api/sessions/{sid}/messages", json={"text": "macro, Fridays off"}).json()
    assert turn["reply"].startswith(  # the web shows every request; say what changed
        "Got it: added “take ECON 2020 (Macroeconomics)”, “Fridays free”."
    )
    assert "Found " in turn["reply"] and "Schedule 1" not in turn["reply"]  # drawn, not listed
    assert turn["view"]["status"] == "ok" and turn["view"]["schedules"]
    assert {r["id"] for r in turn["view"]["rules"]} >= {"c1", "c2"}

    closed = api.delete(f"/api/sessions/{sid}/rules/c2").json()
    assert closed["reply"].startswith("Dropped “Fridays free”.") and provider.calls == 1
    assert api.get(f"/api/sessions/{sid}").json()["rules"] == closed["view"]["rules"]


def test_non_pdf_uploads_and_unknown_sessions_are_refused(tmp_path: Path) -> None:
    api, seen = client(tmp_path, Script())
    assert api.post("/api/sessions", content=b"hello").status_code == 400 and not seen
    assert api.get("/api/sessions/nope").status_code == 404
    assert api.post("/api/sessions/nope/messages", json={"text": "hi"}).status_code == 404


def test_an_unreadable_audit_says_so(tmp_path: Path) -> None:
    def broken(pdf: Path) -> ChatSession:
        raise ValueError("no requirement blocks found")

    api = TestClient(create_app(broken))
    response = api.post("/api/sessions", content=PDF)
    assert (
        response.status_code == 422 and "no requirement blocks found" in response.json()["detail"]
    )


def test_catalog_search_is_read_from_the_session_without_the_llm(tmp_path: Path) -> None:
    provider = Script()
    api, _ = client(tmp_path, provider)
    sid = api.post("/api/sessions", content=PDF).json()["id"]
    found = api.get(f"/api/sessions/{sid}/catalog", params={"q": "macro"}).json()
    assert [c["code"] for c in found["courses"]] == ["ECON 2020"] and provider.calls == 0
    assert api.get("/api/sessions/nope/catalog").status_code == 404


def test_messages_say_which_plan_is_on_screen(tmp_path: Path) -> None:
    api, _ = client(tmp_path, Script(answer()))
    sid = api.post("/api/sessions", content=PDF).json()["id"]
    sent = api.post(f"/api/sessions/{sid}/messages", json={"text": "hi", "plan": 2})
    assert sent.status_code == 200
    assert (
        api.post(f"/api/sessions/{sid}/messages", json={"text": "hi", "plan": -1}).status_code
        == 422
    )
