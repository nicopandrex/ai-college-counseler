"""Term-mode solver: per-type semantics, soft weighting, top-5, minimal infeasible subsets."""

from term_fixtures import STUDENT, TERM, c, spec

from planner_solver.spec import PARAMS, ConstraintType
from planner_solver.term import instructor_matches, solve_term


def best(*constraints):
    result = solve_term(spec(*constraints), TERM, STUDENT)
    assert result.status == "ok", (result.conflict, result.warnings)
    return result.schedules[0]


def all_sections(result) -> list[set[str]]:
    return [set(s.sections) for s in result.schedules]


def test_every_schema_type_has_params() -> None:
    assert set(PARAMS) == set(ConstraintType.__args__)


# -- content ---------------------------------------------------------------------------------


def test_include_and_exclude_course() -> None:
    schedule = best(
        c("c1", "include_course", course="CS 3200"),
        c("c2", "exclude_course", course="ECON 2020"),
        c("c3", "credit_range", min=6, max=9),
    )
    assert "CS 3200" in schedule.courses
    assert "ECON 2020" not in schedule.courses


def test_unplannable_course_is_never_proposed() -> None:
    result = solve_term(spec(c("c1", "include_course", course="CS 1210")), TERM, STUDENT)
    assert result.status == "infeasible"
    assert result.conflict == ["c1"]
    assert any("CS 1210 is already taken" in w for w in result.warnings)


def test_prerequisite_not_met_makes_course_ineligible() -> None:
    result = solve_term(spec(c("c1", "include_course", course="CS 4999")), TERM, STUDENT)
    assert result.status == "infeasible"


def test_satisfy_requirement_is_a_disjunction() -> None:
    schedule = best(
        c("c1", "satisfy_requirement", req_ids=["GENED_HUM", "GENED_SOC"], count=1),
        c("c2", "credit_range", min=3, max=3),
    )
    assert schedule.courses in (["HIST 1010"], ["SOC 1000"])


def test_satisfy_requirement_count_two() -> None:
    schedule = best(
        c("c1", "satisfy_requirement", req_ids=["GENED_HUM", "GENED_SOC", "ENGL_A2"], count=2),
        c("c2", "credit_range", min=6, max=6),
    )
    assert len(set(schedule.requirements_covered) & {"GENED_HUM", "GENED_SOC", "ENGL_A2"}) >= 2


def test_lab_course_takes_one_section_of_each_component() -> None:
    schedule = best(
        c("c1", "include_course", course="BIOL 1400"), c("c2", "credit_range", min=4, max=4)
    )
    assert set(schedule.sections) == {"BIOL 1400 A", "BIOL 1400 L1"}


# -- load / time ---------------------------------------------------------------------------------


def test_credit_range_bounds_total() -> None:
    schedule = best(c("c1", "credit_range", min=12, max=13))
    assert 12 <= schedule.credits <= 13


def test_no_earlier_than_excludes_early_sections() -> None:
    schedule = best(
        c("c1", "include_course", course="CS 3200"),
        c("c2", "no_earlier_than", time="10:30"),
        c("c3", "credit_range", min=3, max=3),
    )
    assert schedule.sections == ["CS 3200 B"]  # the 9:00 MWF section is out


def test_no_earlier_than_limited_to_days() -> None:
    schedule = best(
        c("c1", "include_course", course="CS 3410"),
        c("c2", "no_earlier_than", time="10:00", days=["M", "W", "F"]),
        c("c3", "credit_range", min=3, max=3),
    )
    assert schedule.sections == ["CS 3410 A"]  # TR 8:30 is allowed


def test_no_later_than() -> None:
    schedule = best(
        c("c1", "satisfy_requirement", req_ids=["SCIENCE"]),
        c("c2", "no_later_than", time="17:00"),
        c("c3", "credit_range", min=4, max=4),
    )
    assert schedule.courses == ["BIOL 1400"]  # CHEM's lab runs to 19:30


def test_free_day() -> None:
    schedule = best(c("c1", "free_day", day="F"), c("c2", "credit_range", min=9, max=9))
    assert not any(
        s.startswith(("CS 3200 A", "ECON 2020 A", "ENGL 2010 A", "BIOL")) for s in schedule.sections
    )


def test_free_block() -> None:
    schedule = best(
        c("c1", "include_course", course="CS 3200"),
        c("c2", "free_block", day="T", start="12:00", end="17:00", label="work"),
        c("c3", "credit_range", min=3, max=3),
    )
    assert schedule.sections == ["CS 3200 A"]


def test_instructor_exclusion_scoped_to_course() -> None:
    schedule = best(
        c("c1", "include_course", course="ECON 2020"),
        c("c2", "instructor_preference", name="John Smith", polarity="exclude", course="ECON 2020"),
        c("c3", "credit_range", min=3, max=3),
    )
    assert schedule.sections == ["ECON 2020 B"]


def test_instructor_name_matching_is_fuzzy_but_not_loose() -> None:
    assert instructor_matches("Professor John Smith", "Smith, John A")
    assert instructor_matches("Smith", "Smith, John A")
    assert not instructor_matches("Jane Smith", "Smith, John A")
    assert not instructor_matches("John Smithson", "Smith, John A")


def test_gap_between_classes_min() -> None:
    # CS 3200 B ends 14:30 and HIST starts 14:50 (20 min): too tight for a 30-minute minimum
    schedule = best(
        c("c1", "include_course", course="CS 3200"),
        c("c2", "include_course", course="HIST 1010"),
        c("c3", "gap_between_classes", min_minutes=30),
        c("c4", "credit_range", min=6, max=6),
    )
    assert "CS 3200 A" in schedule.sections  # B would leave only 20 minutes before HIST


def test_gap_between_classes_max() -> None:
    result = solve_term(
        spec(
            c("c1", "include_course", course="CS 3410"),
            c("c2", "include_course", course="HIST 1010"),
            c("c3", "gap_between_classes", max_minutes=120),
            c("c4", "credit_range", min=6, max=6),
        ),
        TERM,
        STUDENT,
    )
    assert result.status == "infeasible"  # 9:45 -> 14:50 is a 5-hour hole on T/R
    # minimal: without the credit cap a third class could fill the hole
    assert sorted(result.conflict) == ["c1", "c2", "c3", "c4"]


def test_max_consecutive_classes() -> None:
    # MWF: ECON A 10:50-11:40 -> ENGL 11:50 is back-to-back; ECON B (TR 11:30) is not
    schedule = best(
        c("c1", "include_course", course="ENGL 2010"),
        c("c2", "include_course", course="ECON 2020"),
        c("c3", "include_course", course="CS 3200"),
        c("c4", "max_consecutive_classes", count=1),
        c("c5", "credit_range", min=9, max=9),
    )
    assert "ECON 2020 B" in schedule.sections


def test_max_consecutive_labs_and_labs_per_day() -> None:
    both_labs = [
        c("c1", "include_course", course="BIOL 1400"),
        c("c2", "include_course", course="CHEM 1400"),
    ]
    result = solve_term(spec(*both_labs, c("c3", "max_labs_per_day", count=1)), TERM, STUDENT)
    assert result.status == "infeasible" and sorted(result.conflict) == ["c1", "c2", "c3"]
    result = solve_term(spec(*both_labs, c("c3", "max_consecutive_labs", count=1)), TERM, STUDENT)
    assert result.status == "infeasible"  # R 13:15-16:15 then 16:30 lab: back-to-back
    assert sorted(result.conflict) == ["c1", "c2", "c3"]


def test_modality_and_open_seats() -> None:
    schedule = best(
        c("c1", "include_course", course="ECON 2020"),
        c("c2", "open_seats_only", value=True),
        c("c3", "credit_range", min=3, max=3),
    )
    assert schedule.sections == ["ECON 2020 B"]
    schedule = best(
        c("c1", "modality", format="hybrid", comparator="at_least", count=1),
        c("c2", "credit_range", min=3, max=3),
    )
    assert schedule.courses == ["SOC 1000"]


def test_counting_constraints() -> None:
    schedule = best(
        c("c1", "subject_limit", subject="CS", comparator="at_least", count=2),
        c("c2", "credit_range", min=6, max=6),
    )
    assert schedule.courses == ["CS 3200", "CS 3410"]
    schedule = best(
        c("c1", "course_attribute", attribute="A2", count=1), c("c2", "credit_range", min=3, max=3)
    )
    assert schedule.courses == ["ENGL 2010"]
    schedule = best(
        c("c1", "course_count_range", min=4, max=4),
        c("c2", "level_distribution", level=1000, comparator="exactly", count=0),
    )
    assert len(schedule.courses) == 4 and all(
        not code.split()[1].startswith("1") for code in schedule.courses
    )


def test_max_days_on_campus() -> None:
    schedule = best(c("c1", "max_days_on_campus", count=2), c("c2", "credit_range", min=6, max=6))
    days = {
        d
        for s in TERM.sections
        if s.section_id in schedule.sections
        for m in s.meetings
        for d in m.days
    }
    assert len(days) <= 2


# -- soft weighting and alternatives --------------------------------------------------------------


def test_soft_constraint_weights_use_power_of_two_scaling() -> None:
    # One weight-5 preference must beat three weight-1 preferences that conflict with it.
    schedule = best(
        c("c1", "include_course", course="CS 3200"),
        c("c2", "credit_range", min=3, max=3),
        c("p5", "no_earlier_than", "soft", 5, time="10:00"),  # wants section B (TR 13:15)
        c("p1a", "free_day", "soft", 1, day="T"),  # these three want section A
        c("p1b", "free_day", "soft", 1, day="R"),
        c("p1c", "no_later_than", "soft", 1, time="12:00"),
    )
    assert schedule.sections == ["CS 3200 B"]
    assert schedule.soft_met == ["p5"]


def test_top_five_schedules_have_distinct_course_sets() -> None:
    result = solve_term(spec(c("c1", "credit_range", min=6, max=6)), TERM, STUDENT)
    assert result.status == "ok" and len(result.schedules) == 5
    course_sets = [tuple(s.courses) for s in result.schedules]
    assert len(set(course_sets)) == 5


# -- infeasibility: minimal conflicting sets, ranked relaxations -----------------------------------


def test_infeasible_time_window_vs_course() -> None:
    result = solve_term(
        spec(
            c("c1", "include_course", course="BIOL 1400"),
            c("c2", "no_earlier_than", time="10:30", weight=3),
            c("c3", "free_day", day="F", weight=2),  # also conflicts with BIOL (MWF lecture)
            c("c4", "include_course", course="SOC 1000"),  # irrelevant: no overlap with BIOL
        ),
        TERM,
        STUDENT,
    )
    assert result.status == "infeasible"
    assert sorted(result.conflict) in (
        ["c1", "c2"],
        ["c1", "c3"],
    )  # each pair alone is a minimal core


def test_infeasible_instructor_vs_seats() -> None:
    result = solve_term(
        spec(
            c("c1", "include_course", course="ECON 2020", weight=5),
            c(
                "c2",
                "instructor_preference",
                name="Ana Diaz",
                polarity="exclude",
                course="ECON 2020",
                weight=4,
            ),
            c("c3", "open_seats_only", value=True, weight=2),
            c("c4", "free_day", day="S"),  # irrelevant
        ),
        TERM,
        STUDENT,
    )
    assert result.status == "infeasible"
    assert sorted(result.conflict) == ["c1", "c2", "c3"]
    assert [r.constraint_id for r in result.relaxations] == ["c3", "c2", "c1"]  # ascending weight
    assert all(r.schedules_unlocked >= 1 for r in result.relaxations)


def test_infeasible_credit_cap_needs_all_four() -> None:
    result = solve_term(
        spec(
            c("i1", "include_course", course="CS 3200"),
            c("i2", "include_course", course="HIST 1010"),
            c("i3", "include_course", course="ENGL 2010"),
            c("cap", "credit_range", min=0, max=6, weight=3),
        ),
        TERM,
        STUDENT,
    )
    assert result.status == "infeasible"
    assert sorted(result.conflict) == ["cap", "i1", "i2", "i3"]
    assert result.relaxations[0].constraint_id == "cap"


def test_worked_example_one_shape() -> None:
    """Reference doc example 1, on the synthetic term."""
    result = solve_term(
        spec(
            c("c1", "include_course", course="CS 3200"),
            c("c2", "include_course", course="ECON 2020"),
            c("c3", "satisfy_requirement", req_ids=["ENGL_A2"], count=1),
            c("c4", "satisfy_requirement", weight=4, req_ids=["GENED_HUM", "GENED_SOC"], count=1),
            c("c5", "no_earlier_than", time="10:30"),
            c(
                "c6",
                "instructor_preference",
                weight=4,
                name="John Smith",
                polarity="exclude",
                course="ECON 2020",
            ),
            c("c7", "credit_range", weight=3, min=12, max=16),
        ),
        TERM,
        STUDENT,
    )
    assert result.status == "ok"
    for schedule in result.schedules:
        assert {"CS 3200", "ECON 2020", "ENGL 2010"} <= set(schedule.courses)
        assert "ECON 2020 A" not in schedule.sections and "CS 3200 A" not in schedule.sections
        assert {"GENED_HUM", "GENED_SOC"} & set(schedule.requirements_covered)


def test_distinct_requires_a_different_course() -> None:
    from term_fixtures import sec

    from planner_solver.domain import Course, RequirementTarget, StudentTerm, TermData

    both = Course(code="ENGL 2600", title="Lit", credits=3, attributes=frozenset({"A2", "HUM"}))
    hist = Course(code="HIST 1010", title="History", credits=3, attributes=frozenset({"HUM"}))
    term = TermData(
        term="2027SP",
        courses={both.code: both, hist.code: hist},
        sections=(
            sec("ENGL 2600 A", "ENGL 2600", "MW", "09:00", "10:15"),
            sec("HIST 1010 A", "HIST 1010", "TR", "09:00", "10:15"),
        ),
    )
    student = StudentTerm(
        counted_courses=frozenset(),
        unplannable_courses=frozenset(),
        open_requirements={
            "A2": RequirementTarget(title="A2", selectors=("@ @ with attribute = A2",)),
            "HUM": RequirementTarget(title="HUM", selectors=("@ @ with attribute = HUM",)),
        },
    )

    def run(distinct: bool, max_credits: int):
        return solve_term(
            spec(
                c("s1", "satisfy_requirement", req_ids=["A2"]),
                c("s2", "satisfy_requirement", req_ids=["HUM"], distinct=distinct),
                c("cap", "credit_range", min=0, max=max_credits),
            ),
            term,
            student,
        )

    assert run(distinct=False, max_credits=3).schedules[0].courses == ["ENGL 2600"]  # double-counts
    assert run(distinct=True, max_credits=3).status == "infeasible"
    assert run(distinct=True, max_credits=6).schedules[0].courses == ["ENGL 2600", "HIST 1010"]


def test_unloaded_prerequisites_are_flagged_not_assumed_met() -> None:
    term = TERM.model_copy(update={"prereqs_loaded": False})
    result = solve_term(spec(c("c1", "credit_range", min=3, max=3)), term, STUDENT)
    assert result.warnings[0].startswith("prerequisites were not checked")


def test_excluded_courses_do_not_count_toward_a_requirement() -> None:
    from planner_solver.domain import RequirementTarget

    target = RequirementTarget(
        title="HUM", selectors=("@ @ with attribute = HUM",), excluded=("HIST 1010",)
    )
    student = STUDENT.model_copy(update={"open_requirements": {"GENED_HUM": target}})
    result = solve_term(spec(c("c1", "satisfy_requirement", req_ids=["GENED_HUM"])), TERM, student)
    assert result.status == "infeasible"  # HIST 1010 was the only HUM course
