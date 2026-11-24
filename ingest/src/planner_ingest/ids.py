"""Deterministic requirement ids.

`satisfy_requirement` constraints reference req_ids, so they must be identical across
re-uploads of the same audit. They are derived from the document structure (block title,
then the labels of the row's ancestors and the row itself), never from LLM output.
"""

from __future__ import annotations

import re

from planner_ingest.layout import AuditLayout, Block

MAX_WORDS = 6
# Dropped before truncating, so the distinguishing tail of a label survives
# ("COMMON GROUND VALUES:1 course with a D1 designation" -> common_ground_values_1_course_d1).
FILLER = {"a", "an", "the", "with", "in", "of", "and", "or", "for", "to", "designation"}


def slug(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in FILLER]
    return "_".join(words[:MAX_WORDS]) or "untitled"


def requirement_ids(layout: AuditLayout) -> dict[str, str]:
    """Map every block_id and row_id to a stable, human-readable req_id."""
    ids: dict[str, str] = {}
    used: set[str] = set()

    def claim(key: str, base: str) -> None:
        candidate, n = base, 1
        while candidate in used:
            n += 1
            candidate = f"{base}_{n}"
        used.add(candidate)
        ids[key] = candidate

    for block in layout.blocks:
        block_slug = slug(block.title)
        claim(block.block_id, block_slug)
        for row in block.rows:
            claim(row.row_id, ".".join([block_slug, *_path(block, row.row_id)]))
    return ids


def _path(block: Block, row_id: str) -> list[str]:
    by_id = {row.row_id: row for row in block.rows}
    labels: list[str] = []
    current = by_id.get(row_id)
    while current is not None:
        labels.append(slug(current.label) if current.label else "courses")
        current = by_id.get(current.parent_id) if current.parent_id else None
    return labels[::-1]
