from planner_chat.evaluate import score


def con(t, enf="hard", w=5, ws="stated", **p):
    return {"id": "c", "type": t, "params": p, "enforcement": enf, "weight": w, "weight_source": ws}


def spec(*constraints, mode="term", oos=()):
    return {"mode": mode, "constraints": list(constraints), "out_of_scope": list(oos)}


def expected(t, enf="hard", w=5, **p):
    return {"type": t, "params": p, "enforcement": enf, "weight": w}


ITEM = {"id": "u", "message": "m", "expected": [expected("no_earlier_than", time="10:30")]}


def test_exact_match_passes_and_weight_tolerance_is_one() -> None:
    assert score(ITEM, spec(con("no_earlier_than", time="10:30"))).passed
    assert score(ITEM, spec(con("no_earlier_than", w=4, time="10:30"))).passed
    result = score(ITEM, spec(con("no_earlier_than", w=3, time="10:30")))
    assert not result.passed and result.category == "weight:no_earlier_than"


def test_failure_categories() -> None:
    assert score(ITEM, spec()).category == "missing:no_earlier_than"
    assert (
        score(ITEM, spec(con("no_earlier_than", time="10:00"))).category == "params:no_earlier_than"
    )
    assert (
        score(ITEM, spec(con("no_earlier_than", "soft", time="10:30"))).category
        == "enforcement:no_earlier_than"
    )
    extra = spec(con("no_earlier_than", time="10:30"), con("free_day", day="F"))
    assert score(ITEM, extra).category == "extra:free_day"
    assert score(ITEM, spec(con("no_earlier_than", time="10:30"), mode="plan")).category == "mode"


def test_param_normalisation() -> None:
    item = {
        "id": "u",
        "message": "m",
        "expected": [
            expected("no_earlier_than", time="09:00", days=["T", "R"]),
            expected(
                "instructor_preference",
                name="Rodrigues",
                polarity="exclude",
                course={"one_of": ["ECON 1400", "ECON 2400"]},
            ),
            expected("satisfy_requirement", req_ids=["A", "B"], count=1),
        ],
    }
    produced = spec(
        con("no_earlier_than", time="9:00", days=["R", "T"]),
        con(
            "instructor_preference",
            name="Professor F. Rodrigues",
            polarity="exclude",
            course="ECON 2400",
        ),
        con(
            "satisfy_requirement", req_ids=["B", "A"], count=1.0, distinct=False
        ),  # extra keys are fine
    )
    assert score(item, produced).passed


def test_default_credit_range_and_allowed_extras_are_not_extras() -> None:
    produced = spec(
        con("no_earlier_than", time="10:30"), con("credit_range", ws="default", min=12, max=16)
    )
    assert score(ITEM, produced).passed
    chill = {
        "id": "u",
        "message": "m",
        "expected": [expected("difficulty_load", "soft", 4, target="light")],
        "allow_extra": ["level_distribution"],
    }
    assert score(
        chill,
        spec(
            con("difficulty_load", "soft", 4, target="light"),
            con("level_distribution", "soft", 3, level=4000, comparator="at_most", count=1),
        ),
    ).passed


def test_alternatives_and_out_of_scope() -> None:
    item = {
        "id": "u",
        "message": "m",
        "expected": [expected("include_course", course="CS 3920")],
        "alternatives": [[expected("satisfy_requirement", req_ids=["SEM"], count=1)]],
    }
    assert score(item, spec(con("satisfy_requirement", req_ids=["SEM"], count=1))).passed
    oos = {"id": "u", "message": "m", "expected": [], "expect_out_of_scope": True}
    assert score(oos, spec(oos=[{"request": "roommate schedule"}])).passed
    assert score(oos, spec()).category == "out_of_scope_missing"
    assert (
        score(oos, spec(con("free_day", day="F"), oos=[{"request": "x"}])).category
        == "extra:free_day"
    )
