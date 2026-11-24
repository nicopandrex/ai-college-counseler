"""Audit PDF -> validated extraction: layout pass, LLM structuring, deterministic checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from planner_ingest.config import load_school_config
from planner_ingest.extraction import ExtractedAudit, llm_output_schema
from planner_ingest.layout import AuditLayout, parse_layout
from planner_ingest.prompts.loader import extraction_system_prompt
from planner_ingest.render import render_for_llm
from planner_ingest.validate import Issue, finalize, review_items
from planner_llm import JsonRequest, LLMError, LLMGateway

PURPOSE = "audit_extraction"


@dataclass
class ExtractionResult:
    audit: ExtractedAudit
    issues: list[Issue]
    layout_warnings: list[str] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        return {
            "audit": self.audit.model_dump(mode="json", by_alias=True),
            "issues": [issue.__dict__ for issue in self.issues],
            "layout_warnings": self.layout_warnings,
            "needs_review": [r.req_id for r in review_items(self.audit)],
        }


def extraction_request(layout: AuditLayout) -> JsonRequest:
    return JsonRequest(
        purpose=PURPOSE,
        system=extraction_system_prompt(),
        user=render_for_llm(layout),
        schema=llm_output_schema(),
        max_tokens=64000,
        effort="high",
    )


def extract_audit(pdf_path: Path, gateway: LLMGateway, school: str = "uvm") -> ExtractionResult:
    config = load_school_config(school)
    layout = parse_layout(pdf_path, config)
    raw = gateway.complete_json(extraction_request(layout))
    try:
        audit = ExtractedAudit.model_validate(raw)
    except ValidationError as exc:
        raise LLMError(f"extraction does not match the output schema: {exc}") from exc
    final, issues = finalize(audit, layout, config)
    return ExtractionResult(final, issues, layout.warnings)
