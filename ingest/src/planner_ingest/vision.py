"""Vision fallback hook. Off the main path by design.

Only two situations may reach it: a page with zero extractable text (a scanned upload), or
a single status icon whose color is not in the school's config. V0 ships the hook with no
implementation: both cases surface as warnings and `unknown` status for human review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from planner_ingest.config import IconStatus


class VisionFallback(Protocol):
    def transcribe_page(self, pdf_path: Path, page_no: int) -> str | None: ...

    def classify_icon(
        self, pdf_path: Path, page_no: int, region: tuple[float, float, float]
    ) -> IconStatus | None: ...


class NoVisionFallback:
    def transcribe_page(self, pdf_path: Path, page_no: int) -> str | None:
        return None

    def classify_icon(
        self, pdf_path: Path, page_no: int, region: tuple[float, float, float]
    ) -> IconStatus | None:
        return None
