"""M5: the 8 validation rules from docs/constraint-spec-reference.md (+ already-taken courses)."""

from typing import Any

import pytest

from planner_solver.validation import SchoolCapabilities, ValidationContext, validate_spec

CTX = ValidationContext(
    course_codes=frozenset({"CS 3200", "CS 3050", "ECON 2020", "ENGL 2010"}),
    requirement_ids=frozenset({"ENGL_A2", "GENED_HUM", "GENED_SOC"}),
    unplannable_courses=frozenset({"CS 3050"}),
    capabilities=SchoolCapabilities(
        unavailable={"section_size": "UVM schedule data has no seat caps"}
    ),
)


def c(
    cid: str, ctype: str, enforcement: str = "hard", weight: int = 5, **extra: Any
) -> dict[str, Any]:
    params = extra.pop("params", {})
    return {
        "id": cid,
        "type": ctype,
        "params": params,
        "enforcement": enforcement,
        "weight": weight,
        **extra,
    }


def raw(*constraints: dict[str, Any], mode: str = "term", **top: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "spec_version": "0.1",
        "mode": mode,
        "restatement": "r",
        "constraints": list(constraints),
    }
    if mode == "term":
        spec["target_term"] = "2027SP"
    spec.update(top)
    return spec


def rules(result) -> list[int]:
    return sorted(i.rule for i in result.errors)


def test_valid_spec_passes_unchanged() -> None:
    result = validate_spec(raw(c("c1", "include_course", params={"course": "CS 3200"})), CTX)
    assert result.ok and result.errors == [] and result.spec is not None


def test_contract_violations_are_rejected_before_anything_else() -> None:
    bad = raw(c("c1", "include_course", params={"course": "CS 3200"}, colour="red"))
    result = validate_spec(bad, CTX)
    assert not result.ok and rules(result) == [0]  # rule 0: the JSON Schema contract itself


# rule 1 -----------------------------------------------------------------------------------------


def test_rule1_course_formatting_is_normalised() -> None:
    result = validate_spec(raw(c("c1", "include_course", params={"course": "cs3200"})), CTX)
    assert result.ok
    assert result.spec.constraints[0].params["course"] == "CS 3200"
    assert any("cs3200" in n for n in result.notes)


def test_rule1_near_miss_is_rejected_with_suggestion_not_guessed() -> None:
    result = validate_spec(raw(c("c1", "include_course", params={"course": "CS 3205"})), CTX)
    assert rules(result) == [1]
    assert "CS 3200" in result.errors[0].message


def test_rule1_already_taken_course_is_an_error() -> None:
    result = validate_spec(raw(c("c1", "include_course", params={"course": "CS 3050"})), CTX)
    assert rules(result) == [1]
    assert "already" in result.errors[0].message


def test_rule1_instructor_course_is_checked_too() -> None:
    con = c(
        "c1",
        "instructor_preference",
        params={"name": "Smith", "polarity": "exclude", "course": "ECON 9999"},
    )
    assert rules(validate_spec(raw(con), CTX)) == [1]


# rule 2 -----------------------------------------------------------------------------------------


def test_rule2_req_ids_must_belong_to_this_student() -> None:
    con = c("c1", "satisfy_requirement", params={"req_ids": ["ENGL_A2", "GENED_MATH"], "count": 1})
    result = validate_spec(raw(con), CTX)
    assert rules(result) == [2] and "GENED_MATH" in result.errors[0].message


# rules 3 and 4 ------------------------------------------------------------------------------------


def test_rule3_plan_only_type_rejected_in_term_mode() -> None:
    con = c("c1", "target_graduation_term", params={"term": "2029SP"})
    assert rules(validate_spec(raw(con), CTX)) == [3]


def test_rule3_term_only_type_rejected_in_plan_mode() -> None:
    con = c("c1", "free_day", params={"day": "F"})
    assert rules(validate_spec(raw(con, mode="plan"), CTX)) == [3]


def test_rule4_target_term_iff_term_mode() -> None:
    term_without = raw(c("c1", "free_day", params={"day": "F"}))
    del term_without["target_term"]
    assert rules(validate_spec(term_without, CTX)) == [4]
    plan_with = raw(mode="plan", target_term="2027SP")
    assert rules(validate_spec(plan_with, CTX)) == [4]


# rule 5 -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ctype,params",
    [
        ("no_earlier_than", {"time": "10:30am"}),
        ("free_day", {"day": "Friday"}),
        ("credit_range", {"min": 12}),
        ("satisfy_requirement", {"req_ids": []}),
        ("include_course", {"course": "CS 3200", "extra": 1}),
    ],
)
def test_rule5_per_type_params(ctype: str, params: dict[str, Any]) -> None:
    assert rules(validate_spec(raw(c("c1", ctype, params=params)), CTX)) == [5]


# rule 6 -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "constraints",
    [
        [
            c("a", "no_earlier_than", params={"time": "14:00"}),
            c("b", "no_later_than", params={"time": "12:00"}),
        ],
        [c("a", "credit_range", params={"min": 16, "max": 12})],
        [
            c("a", "include_course", params={"course": "CS 3200"}),
            c("b", "exclude_course", params={"course": "CS 3200"}),
        ],
        [c("a", "free_block", params={"day": "T", "start": "17:00", "end": "14:00"})],
    ],
)
def test_rule6_cheap_contradictions_between_hard_constraints(constraints) -> None:
    result = validate_spec(raw(*constraints), CTX)
    assert rules(result) == [6]


def test_rule6_ignores_soft_or_day_disjoint_pairs() -> None:
    disjoint = [
        c("a", "no_earlier_than", params={"time": "14:00", "days": ["M"]}),
        c("b", "no_later_than", params={"time": "12:00", "days": ["T"]}),
    ]
    assert validate_spec(raw(*disjoint), CTX).ok
    soft = [
        c("a", "no_earlier_than", params={"time": "14:00"}),
        c("b", "no_later_than", "soft", 2, params={"time": "12:00"}),
    ]
    assert validate_spec(raw(*soft), CTX).ok


# rule 7 -----------------------------------------------------------------------------------------


def test_rule7_low_confidence_gets_a_question() -> None:
    con = c(
        "c1",
        "no_earlier_than",
        "soft",
        3,
        params={"time": "10:00"},
        confidence=0.5,
        weight_source="inferred",
        source_text="nothing too early",
    )
    result = validate_spec(raw(con), CTX)
    assert result.ok
    (question,) = result.spec.clarifications
    assert question.constraint_id == "c1" and question.blocking is False
    assert question.kind in ("weight_check", "ambiguity")


def test_rule7_existing_question_is_not_duplicated_and_cap_is_two() -> None:
    low = [
        c(f"c{i}", "free_day", "soft", 2, params={"day": d}, confidence=0.4)
        for i, d in enumerate("MTWR")
    ]
    existing = {"question": "Which day?", "kind": "ambiguity", "constraint_id": "c0"}
    result = validate_spec(raw(*low, clarifications=[existing]), CTX)
    assert len(result.spec.clarifications) == 2
    assert result.spec.clarifications[0].question == "Which day?"


# rule 8 -----------------------------------------------------------------------------------------


def test_rule8_unsupported_data_is_dropped_and_reported_honestly() -> None:
    con = c("c1", "section_size", params={"max_enrollment": 30}, source_text="small classes")
    result = validate_spec(raw(con, c("c2", "free_day", params={"day": "F"})), CTX)
    assert result.ok
    assert [x.id for x in result.spec.constraints] == ["c2"]
    (oos,) = result.spec.out_of_scope
    assert oos.user_text == "small classes" and "seat caps" in oos.request


def test_packaged_contract_matches_docs() -> None:
    import json
    from pathlib import Path

    from planner_solver.validation import contract_schema

    docs = Path(__file__).resolve().parents[2] / "docs" / "constraint-spec.schema.json"
    assert contract_schema() == json.loads(docs.read_text())


def test_full_time_credit_default_added_when_unstated() -> None:
    ctx = ValidationContext(**{**CTX.__dict__, "default_credit_range": (12, 18)})
    result = validate_spec(raw(c("c1", "free_day", params={"day": "F"})), ctx)
    added = [x for x in result.spec.constraints if x.type == "credit_range"]
    assert len(added) == 1
    assert added[0].params == {"min": 12, "max": 18}
    assert (added[0].enforcement, added[0].weight_source) == ("hard", "default")


def test_stated_credit_range_is_kept() -> None:
    ctx = ValidationContext(**{**CTX.__dict__, "default_credit_range": (12, 18)})
    stated = c(
        "c1", "credit_range", params={"min": 9, "max": 10}, source_text="just 9 or 10 credits"
    )
    result = validate_spec(raw(stated), ctx)
    assert [x.params for x in result.spec.constraints] == [{"min": 9, "max": 10}]


def test_default_load_preference_is_soft_and_separate() -> None:
    ctx = ValidationContext(
        **{**CTX.__dict__, "default_credit_range": (12, 19), "preferred_credit_range": (12, 16)}
    )
    result = validate_spec(raw(c("c1", "free_day", params={"day": "F"})), ctx)
    loads = {x.id: x for x in result.spec.constraints if x.type == "credit_range"}
    assert (
        loads["default_credits"].params == {"min": 12, "max": 19}
        and loads["default_credits"].enforcement == "hard"
    )
    preferred = loads["default_load_preference"]
    assert preferred.params == {"min": 12, "max": 16} and preferred.enforcement == "soft"
    assert preferred.weight_source == "default"


# consumer-facing checks ------------------------------------------------------------------------

TAUGHT = ValidationContext(
    course_codes=CTX.course_codes,
    requirement_ids=CTX.requirement_ids,
    unplannable_courses=frozenset({"CS 3050", "ENGL 2010"}),
    course_status={"CS 3050": "complete", "ENGL 2010": "in_progress"},  # audit statuses
    instructors={"CS 3200": frozenset({"L. Dion"}), "ECON 2020": frozenset({"Smith, John A"})},
    default_credit_range=(12, 19),
    preferred_credit_range=(12, 16),
)


def test_taken_course_says_which_way_it_was_taken() -> None:
    done = validate_spec(raw(c("c1", "include_course", params={"course": "CS 3050"})), TAUGHT)
    now = validate_spec(raw(c("c1", "include_course", params={"course": "ENGL 2010"})), TAUGHT)
    assert done.errors[0].message == "you've already completed CS 3050"
    assert now.errors[0].message == "you're taking ENGL 2010 now"


def test_unknown_instructor_is_caught_with_a_suggestion() -> None:
    con = c("c1", "instructor_preference", params={"name": "Dionne", "polarity": "include"})
    result = validate_spec(raw(con), TAUGHT)
    assert rules(result) == [1]
    assert "Dionne" in result.errors[0].message and "Dion" in result.errors[0].message


def test_known_instructor_passes_and_initials_match() -> None:
    con = c("c1", "instructor_preference", params={"name": "Professor Dion", "polarity": "include"})
    assert validate_spec(raw(con), TAUGHT).ok


def test_wanting_an_instructor_for_a_course_they_dont_teach_is_an_error() -> None:
    params = {"name": "Dion", "polarity": "include", "course": "ECON 2020"}
    result = validate_spec(raw(c("c1", "instructor_preference", params=params)), TAUGHT)
    assert rules(result) == [1] and "ECON 2020" in result.errors[0].message


def test_avoiding_an_instructor_who_doesnt_teach_it_is_just_a_note() -> None:
    params = {"name": "Dion", "polarity": "exclude", "course": "ECON 2020"}
    result = validate_spec(raw(c("c1", "instructor_preference", params=params)), TAUGHT)
    assert result.ok and any("Dion" in n for n in result.notes)


def test_a_one_sided_range_is_completed_from_the_defaults() -> None:
    at_most = c("c1", "course_count_range", params={"max": 3}, source_text="3 classes max")
    credits = c("c2", "credit_range", params={"min": 15}, source_text="at least 15 credits")
    result = validate_spec(raw(at_most, credits), TAUGHT)
    assert result.ok
    params = {con.id: con.params for con in result.spec.constraints}
    assert params["c1"] == {"min": 1, "max": 3} and params["c2"] == {"min": 15, "max": 19}


def test_a_light_load_aims_for_the_low_end_of_full_time() -> None:
    light = c("c1", "difficulty_load", "soft", 3, params={"target": "light"})
    result = validate_spec(raw(light), TAUGHT)
    preferred = next(x for x in result.spec.constraints if x.id == "default_load_preference")
    assert preferred.params == {"min": 12, "max": 13}


def test_notes_are_written_for_the_student_without_internal_ids() -> None:
    result = validate_spec(raw(c("c1", "include_course", params={"course": "cs3200"})), TAUGHT)
    assert result.notes[0] == "read “cs3200” as CS 3200"
    assert not any("c1" in n or "default_" in n for n in result.notes)
