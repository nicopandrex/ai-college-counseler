"""Per-school DegreeWorks rendering config (Ellucian lets each school theme the audit)."""

from __future__ import annotations

from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict

IconStatus = Literal[
    "complete", "incomplete", "in_progress", "nearly_complete", "prereq_needed", "unknown"
]
RequirementStatus = Literal["complete", "in_progress", "incomplete", "unknown"]


class IconColor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rgb: tuple[float, ...]
    paint: Literal["fill", "stroke"]
    status: IconStatus


class SchoolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school_id: str
    name: str
    icon_margin_x: float
    color_tolerance: float
    icon_colors: list[IconColor]
    neutral_colors: list[tuple[float, ...]]
    indent_base_x: float
    indent_step: float
    block_title_min_size: float
    column_header_size: float
    default_content_x: float
    status_words: dict[str, RequirementStatus]
    in_progress_grades: list[str]
    preregistered_grades: list[str]
    summary_fields: list[str]
    legend_label: str


def load_school_config(school_id: str) -> SchoolConfig:
    text = (
        resources.files("planner_ingest.schools")
        .joinpath(f"{school_id}.json")
        .read_text(encoding="utf-8")
    )
    return SchoolConfig.model_validate_json(text)
