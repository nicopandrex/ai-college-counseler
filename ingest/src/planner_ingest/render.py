"""Render the deterministic layout as the LLM's input (the user message).

Every line is document text; the only additions are structural tags the system prompt
explains: block headers, the icon status read from the vector icon, nesting by indentation,
and `COURSE` lines with columns separated by `|`.
"""

from __future__ import annotations

from planner_ingest.layout import AuditLayout, CourseLine, Row


def _course(course: CourseLine) -> str:
    credits = "" if course.credits is None else f"{course.credits:g}"
    if course.in_progress_marker:
        credits = f"({credits})"
    parts = [course.code, course.title, course.grade, credits, course.term]
    if course.repeated:
        parts.append(f"repeated: {course.repeated}")
    line = "COURSE " + " | ".join(parts)
    if course.satisfied_by:
        line += f" || {course.satisfied_by}"
    return line


def _row(row: Row) -> list[str]:
    pad = "  " * (row.level or 0)
    tag = f"[icon: {row.icon_status}]" if row.icon_status else "[no icon]"
    lines = [f"{pad}ROW {tag} {row.label}".rstrip()]
    if row.content:
        lines.append(f"{pad}    {' '.join(row.content)}")
    lines.extend(f"{pad}    {_course(c)}" for c in row.courses)
    return lines


def render_for_llm(layout: AuditLayout) -> str:
    out = ["AUDIT SUMMARY"]
    out.extend(f"{label}: {value}" for label, value in layout.summary.items())
    for block in layout.blocks:
        out.append("")
        status = f" [block status: {block.status_text}]" if block.status_text else ""
        out.append(f"BLOCK {block.title}{status}")
        out.extend(f"    {info}" for info in block.info)
        for row in block.rows:
            out.extend(_row(row))
    if layout.warnings:
        out.append("")
        out.append("EXTRACTION WARNINGS")
        out.extend(f"- {w}" for w in layout.warnings)
    return "\n".join(out) + "\n"
