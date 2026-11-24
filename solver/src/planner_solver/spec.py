"""The constraint-spec contract (docs/constraint-spec.schema.json) plus per-type params.

`ConstraintSpec` mirrors the JSON Schema exactly; the schema leaves `params` loose by design,
so `PARAMS[type]` holds the per-type models from docs/constraint-spec-reference.md.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from planner_solver.domain import Day

ConstraintType = Literal[
    "include_course",
    "exclude_course",
    "satisfy_requirement",
    "course_attribute",
    "level_distribution",
    "subject_limit",
    "difficulty_load",
    "credit_range",
    "course_count_range",
    "no_earlier_than",
    "no_later_than",
    "free_day",
    "free_block",
    "max_days_on_campus",
    "max_consecutive_classes",
    "gap_between_classes",
    "compactness",
    "instructor_preference",
    "modality",
    "section_size",
    "campus",
    "travel_time",
    "open_seats_only",
    "max_consecutive_labs",
    "max_labs_per_day",
    "target_graduation_term",
    "credits_per_term",
    "term_availability",
    "reserved_term",
    "add_program",
    "front_load_prereqs",
    "balance_difficulty",
    "keep_option_open",
]

PLAN_ONLY: frozenset[str] = frozenset(
    {
        "target_graduation_term",
        "credits_per_term",
        "term_availability",
        "reserved_term",
        "add_program",
        "front_load_prereqs",
        "balance_difficulty",
        "keep_option_open",
    }
)

WEIGHT_SCALE = {5: 16, 4: 8, 3: 4, 2: 2, 1: 1}  # powers of two (reference doc)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Constraint(_Strict):
    id: str
    type: ConstraintType
    params: dict[str, Any]
    enforcement: Literal["hard", "soft"]
    weight: int = Field(ge=1, le=5)
    weight_source: Literal["stated", "inferred", "default", "user_confirmed"] = "inferred"
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_text: str | None = None
    data_dependency: Literal["reliable", "estimated", "may_be_missing"] = "reliable"


class Clarification(_Strict):
    question: str
    kind: Literal["weight_check", "ambiguity", "missing_info", "tradeoff"]
    constraint_id: str | None = None
    options: list[str] | None = None
    blocking: bool = False


class OutOfScope(BaseModel):
    model_config = ConfigDict(extra="allow")  # the schema allows extra properties here

    request: str
    user_text: str | None = None


class ConstraintSpec(_Strict):
    spec_version: Literal["0.1"] | None = None
    mode: Literal["term", "plan"]
    target_term: str | None = None
    constraints: list[Constraint]
    clarifications: list[Clarification] = []
    restatement: str
    out_of_scope: list[OutOfScope] = []


# -- per-type params ------------------------------------------------------------------------

TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
Comparator = Literal["at_least", "at_most", "exactly"]


def minutes(hhmm: str) -> int:
    match = TIME.match(hhmm)
    if not match:
        raise ValueError(f"time must be HH:MM, got {hhmm!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


class _Params(_Strict):
    pass


class _TimeParams(_Params):
    @field_validator("time", "start", "end", check_fields=False)
    @classmethod
    def _hhmm(cls, value: str) -> str:
        minutes(value)
        return value


class CourseParams(_Params):
    course: str


class SatisfyRequirementParams(_Params):
    req_ids: list[str] = Field(min_length=1)
    count: int = Field(default=1, ge=1)
    distinct: bool = False  # True: covered by courses not used for other satisfy_requirement


class CourseAttributeParams(_Params):
    attribute: str
    count: int = Field(ge=0)
    comparator: Comparator = "at_least"


class LevelDistributionParams(_Params):
    level: int  # 1000-wide band, e.g. 4000 = 4000-4999
    comparator: Comparator
    count: int = Field(ge=0)


class SubjectLimitParams(_Params):
    subject: str
    comparator: Comparator
    count: int = Field(ge=0)


class DifficultyLoadParams(_Params):
    target: Literal["light", "moderate", "heavy"]


class RangeParams(_Params):
    min: float = Field(ge=0)
    max: float = Field(ge=0)


class TimeBoundParams(_TimeParams):
    time: str
    days: list[Day] | None = None


class FreeDayParams(_Params):
    day: Day


class FreeBlockParams(_TimeParams):
    day: Day
    start: str
    end: str
    label: str | None = None


class CountParams(_Params):
    count: int = Field(ge=0)


class ConsecutiveParams(_Params):
    count: int = Field(ge=1)
    days: list[Day] | None = None


class GapParams(_Params):
    min_minutes: int | None = Field(default=None, ge=0)
    max_minutes: int | None = Field(default=None, ge=0)


class CompactnessParams(_Params):
    direction: Literal["compact", "spread"]


class InstructorParams(_Params):
    name: str
    polarity: Literal["include", "exclude"]
    course: str | None = None


class ModalityParams(_Params):
    format: Literal["online", "in_person", "hybrid"]
    comparator: Comparator | None = None  # omitted: every course in this format
    count: int | None = Field(default=None, ge=0)


class SectionSizeParams(_Params):
    max_enrollment: int = Field(ge=1)


class CampusParams(_Params):
    campus: str
    polarity: Literal["only", "exclude"]


class TravelTimeParams(_Params):
    min_minutes_between_campuses: int = Field(ge=0)


class OpenSeatsParams(_Params):
    value: bool


class TermParams(_Params):
    term: str


class CreditsPerTermParams(_Params):
    min: float = Field(ge=0)
    max: float = Field(ge=0)
    terms: list[str] | None = None


class TermAvailabilityParams(_Params):
    summer: bool | None = None
    winter: bool | None = None


class ReservedTermParams(_Params):
    term: str
    reason: str | None = None
    max_credits: float = Field(default=0, ge=0)


class AddProgramParams(_Params):
    program_id: str
    action: str


class EmptyParams(_Params):
    pass


class ProgramParams(_Params):
    program_id: str


PARAMS: dict[str, type[_Params]] = {
    "include_course": CourseParams,
    "exclude_course": CourseParams,
    "satisfy_requirement": SatisfyRequirementParams,
    "course_attribute": CourseAttributeParams,
    "level_distribution": LevelDistributionParams,
    "subject_limit": SubjectLimitParams,
    "difficulty_load": DifficultyLoadParams,
    "credit_range": RangeParams,
    "course_count_range": RangeParams,
    "no_earlier_than": TimeBoundParams,
    "no_later_than": TimeBoundParams,
    "free_day": FreeDayParams,
    "free_block": FreeBlockParams,
    "max_days_on_campus": CountParams,
    "max_consecutive_classes": ConsecutiveParams,
    "gap_between_classes": GapParams,
    "compactness": CompactnessParams,
    "instructor_preference": InstructorParams,
    "modality": ModalityParams,
    "section_size": SectionSizeParams,
    "campus": CampusParams,
    "travel_time": TravelTimeParams,
    "open_seats_only": OpenSeatsParams,
    "max_consecutive_labs": ConsecutiveParams,
    "max_labs_per_day": CountParams,
    "target_graduation_term": TermParams,
    "credits_per_term": CreditsPerTermParams,
    "term_availability": TermAvailabilityParams,
    "reserved_term": ReservedTermParams,
    "add_program": AddProgramParams,
    "front_load_prereqs": EmptyParams,
    "balance_difficulty": EmptyParams,
    "keep_option_open": ProgramParams,
}


def parse_params(constraint: Constraint) -> _Params:
    return PARAMS[constraint.type].model_validate(constraint.params)
