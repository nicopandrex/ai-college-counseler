import json
from pathlib import Path

from planner_chat.translator import (
    TranslatorContext,
    system_prompt,
    to_contract,
    translate,
    user_message,
)
from planner_llm import CacheMode, JsonRequest, LLMGateway
from planner_solver.validation import ValidationContext, validate_spec

CONTEXT = TranslatorContext(
    target_term="2027SP",
    open_requirements=[("GENED_S1", "Social Sciences (S1)")],
    catalog=[("ECON 1400", "Principles of Macroeconomics")],
)
DOCS = Path(__file__).resolve().parents[2] / "docs" / "constraint-spec-reference.md"


def raw_output(**overrides):
    out = {
        "spec_version": "0.1",
        "mode": "term",
        "target_term": "2027SP",
        "restatement": "Macro, no 8ams.",
        "constraints": [
            {
                "id": "c1",
                "type": "include_course",
                "params_json": '{"course": "ECON 1400"}',
                "enforcement": "hard",
                "weight": 4,
                "weight_source": "stated",
                "confidence": 0.9,
                "source_text": "macro",
                "data_dependency": "reliable",
            },
            {
                "id": "c2",
                "type": "no_earlier_than",
                "params_json": '{"time": "09:00"}',
                "enforcement": "soft",
                "weight": 3,
                "weight_source": "inferred",
                "confidence": 0.8,
                "source_text": "no 8ams",
                "data_dependency": "reliable",
            },
        ],
        "clarifications": [
            {
                "question": "q?",
                "kind": "weight_check",
                "constraint_id": None,
                "options": [],
                "blocking": False,
            }
        ],
        "out_of_scope": [],
    }
    out.update(overrides)
    return out


def test_output_becomes_a_valid_contract_instance() -> None:
    translation = to_contract(raw_output())
    assert translation.problems == []
    assert translation.spec["constraints"][0]["params"] == {"course": "ECON 1400"}
    assert "constraint_id" not in translation.spec["clarifications"][0]  # nulls dropped
    ctx = ValidationContext(
        course_codes=frozenset({"ECON 1400"}),
        requirement_ids=frozenset(),
        unplannable_courses=frozenset(),
    )
    assert validate_spec(translation.spec, ctx).ok


def test_malformed_params_json_is_reported_not_guessed() -> None:
    bad = raw_output()
    bad["constraints"][1]["params_json"] = "time 09:00"
    translation = to_contract(bad)
    assert [c["id"] for c in translation.spec["constraints"]] == ["c1"]
    assert translation.problems and "c2" in translation.problems[0]


def test_plan_mode_has_no_target_term() -> None:
    spec = to_contract(raw_output(mode="plan", target_term=None, constraints=[])).spec
    assert "target_term" not in spec


def test_prompt_contains_the_whole_reference_and_context() -> None:
    assert DOCS.read_text() in system_prompt()
    user = user_message("macro please", CONTEXT, prior={"constraints": []})
    assert (
        "GENED_S1: Social Sciences (S1)" in user
        and "ECON 1400 — Principles of Macroeconomics" in user
    )
    assert "PRIOR SPEC:" in user and user.rstrip().endswith("macro please")


def test_translate_goes_through_the_gateway(tmp_path: Path) -> None:
    class Stub:
        name = "stub"

        def complete_json(self, request: JsonRequest, model: str) -> str:
            assert request.purpose == "translate"
            return json.dumps(raw_output())

    gateway = LLMGateway(Stub(), "m", tmp_path, CacheMode.LIVE)
    assert translate("macro, no 8ams", CONTEXT, gateway).spec["mode"] == "term"


def test_a_stray_quote_after_a_complete_object_is_tolerated() -> None:
    odd = raw_output()
    odd["constraints"][1]["params_json"] = '{"time": "09:00"}"'
    assert to_contract(odd).spec["constraints"][1]["params"] == {"time": "09:00"}


def test_anything_else_after_the_object_is_still_rejected() -> None:
    odd = raw_output()
    odd["constraints"][1]["params_json"] = '{"time": "09:00"} or maybe 10'
    assert to_contract(odd).problems
