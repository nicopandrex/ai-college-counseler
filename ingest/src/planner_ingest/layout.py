"""Deterministic DegreeWorks PDF layout pass (no LLM, no vision on the main path).

Structure recovered from geometry:
- table rows (pdfplumber cell boxes) are the coarse unit;
- each status icon inside a row anchors one requirement sub-row; text lines are assigned to
  the icon whose vertical band contains them;
- characters are split into the label column and the content column by x position *before*
  words are formed (word extraction alone splices "additional" + "CS" across the boundary);
- course lines are parsed by the x positions of each block's own column-header row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber
from pdfplumber.page import Page

from planner_ingest.config import IconStatus, SchoolConfig
from planner_ingest.icons import Icon, extract_icons, indent_level
from planner_ingest.vision import NoVisionFallback, VisionFallback

LINE_TOLERANCE = 2.0
TEXT_HALF_HEIGHT = 4.0  # 8pt text: a line's visual middle is ~4pt below its top
COURSE_CODE = re.compile(r"^[A-Z]{2,5} [0-9X]{4}[A-Z]?$")
TERM = re.compile(r"^(Fall|Spring|Summer|Winter) \d{4}$")
CREDITS = re.compile(r"^\(?(\d+(?:\.\d+)?)\)?$")
COLUMN_NAMES = ("Course", "Title", "Grade", "Credits", "Term", "Repeated")


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bold: bool
    size: float


@dataclass(frozen=True)
class Line:
    top: float
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return self.words[0].x0


@dataclass(frozen=True)
class Columns:
    code: float
    title: float
    grade: float
    credits: float
    term: float
    repeated: float


@dataclass
class CourseLine:
    code: str
    title: str
    grade: str
    credits: float | None
    term: str
    repeated: str
    in_progress_marker: bool  # credits shown in parentheses, e.g. "(3)"
    source_text: str
    satisfied_by: str | None = None  # transfer-equivalence line ("Satisfied by: ...")


@dataclass
class Row:
    row_id: str
    page: int  # 1-based
    top: float
    level: int | None
    icon_status: IconStatus | None
    label: str
    content: list[str] = field(default_factory=list)
    courses: list[CourseLine] = field(default_factory=list)
    parent_id: str | None = None

    @property
    def still_needed(self) -> str | None:
        text = " ".join(self.content)
        start = text.find("Still needed:")
        return text[start:] if start >= 0 else None

    @property
    def text(self) -> str:
        parts = [self.label, *self.content]
        for course in self.courses:
            parts.append(course.source_text)
            if course.satisfied_by:
                parts.append(course.satisfied_by)
        return " ".join(p for p in parts if p)


@dataclass
class Block:
    block_id: str
    title: str
    page: int
    status_text: str | None
    info: list[str] = field(default_factory=list)
    columns: Columns | None = None
    rows: list[Row] = field(default_factory=list)


@dataclass
class AuditLayout:
    summary: dict[str, str]
    blocks: list[Block]
    warnings: list[str]

    @property
    def rows(self) -> list[Row]:
        return [row for block in self.blocks for row in block.rows]

    @property
    def full_text(self) -> str:
        parts = [f"{k} {v}" for k, v in self.summary.items()]
        for block in self.blocks:
            parts.extend([block.title, block.status_text or "", *block.info])
            parts.extend(row.text for row in block.rows)
        return " ".join(p for p in parts if p)


def _words(page: Page) -> list[Word]:
    raw = page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False)
    return [
        Word(w["text"], w["x0"], w["x1"], w["top"], w["fontname"].endswith("Bold"), w["size"])
        for w in raw
    ]


def _lines(words: list[Word]) -> list[Line]:
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(lines[-1][0].top - word.top) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [Line(ws[0].top, tuple(sorted(ws, key=lambda w: w.x0))) for ws in lines]


def _split_columns(cell: Page, content_x: float) -> tuple[list[Word], list[Word]]:
    def is_label(obj: dict[str, Any]) -> bool:
        return obj.get("object_type") != "char" or obj["x0"] < content_x

    def is_content(obj: dict[str, Any]) -> bool:
        return obj.get("object_type") != "char" or obj["x0"] >= content_x

    return _words(cell.filter(is_label)), _words(cell.filter(is_content))


class _Parser:
    def __init__(self, config: SchoolConfig, vision: VisionFallback, pdf_path: Path) -> None:
        self.config = config
        self.vision = vision
        self.pdf_path = pdf_path
        self.summary: dict[str, str] = {}
        self.blocks: list[Block] = []
        self.warnings: list[str] = []
        self.row_count = 0
        self.done = False

    # -- top level ----------------------------------------------------------------------
    def parse_page(self, page: Page, page_no: int) -> None:
        if not page.chars:
            text = self.vision.transcribe_page(self.pdf_path, page_no)
            if text is None:
                self.warnings.append(f"page {page_no}: no text layer; vision fallback unavailable")
            return
        icons = extract_icons(page.curves, self.config)
        claimed: set[int] = set()
        for table in page.find_tables():
            for table_row in table.rows:
                if self.done:
                    return
                bbox = table_row.bbox
                cell_icons = [
                    i
                    for i in icons
                    if bbox[1] - 1 <= i.center <= bbox[3] + 1 and id(i) not in claimed
                ]
                claimed.update(id(i) for i in cell_icons)
                # Crop rows to the full page width: text can sit exactly on the table edge.
                band = (0, bbox[1], page.width, bbox[3])
                self.parse_cell(page.within_bbox(band), bbox, cell_icons, page_no)
        for icon in icons:
            if id(icon) not in claimed and not self.done:
                self.warnings.append(
                    f"page {page_no}: {icon.status} icon at y={icon.top:.0f} outside any table row"
                )

    def parse_cell(
        self, cell: Page, bbox: tuple[float, ...], icons: list[Icon], page_no: int
    ) -> None:
        all_lines = _lines(_words(cell))
        if not all_lines:
            return
        if all_lines[0].text.startswith(self.config.legend_label):
            self.done = True  # legend + disclaimer follow; nothing more to extract
            return
        title_words = [
            w for w in all_lines[0].words if w.bold and w.size >= self.config.block_title_min_size
        ]
        if title_words:
            self.start_block(all_lines, title_words, page_no)
            return
        if not self.blocks:
            self.parse_summary(all_lines)
            return
        block = self.blocks[-1]
        content_x = block.columns.code if block.columns else self.config.default_content_x
        label_words, content_words = _split_columns(cell, content_x)
        label_lines, content_lines = _lines(label_words), _lines(content_words)
        if icons:
            self.add_icon_rows(block, icons, label_lines, content_lines, bbox, page_no)
        else:
            self.add_row(block, page_no, bbox[1], None, None, label_lines, content_lines)

    # -- blocks and summary -------------------------------------------------------------
    def start_block(self, lines: list[Line], title_words: list[Word], page_no: int) -> None:
        title = " ".join(w.text for w in title_words)
        status_text = None
        info: list[str] = []
        columns = None
        for line in lines:
            words = [w for w in line.words if w not in title_words]
            header = [
                w for w in words if w.bold and abs(w.size - self.config.column_header_size) < 0.5
            ]
            if {w.text for w in header} >= set(COLUMN_NAMES):
                pos = {w.text: w.x0 for w in header}
                columns = Columns(*(pos[name] for name in COLUMN_NAMES))
                words = [w for w in words if w not in header]
            for word in words:
                if word.text in self.config.status_words and status_text is None:
                    status_text = word.text
            rest = " ".join(w.text for w in words if w.text != status_text)
            if rest:
                info.append(rest)
        block_id = f"b{len(self.blocks) + 1}"
        self.blocks.append(Block(block_id, title, page_no, status_text, info, columns))

    def parse_summary(self, lines: list[Line]) -> None:
        """Allow-listed `Label value` pairs only; names, IDs and advisors are never kept."""
        allowed = set(self.config.summary_fields)
        for index, line in enumerate(lines):
            pairs = _label_value_pairs(line)
            if not pairs:
                continue
            nxt = lines[index + 1] if index + 1 < len(lines) else None
            if nxt and _label_value_pairs(nxt) and not nxt.words[0].bold:
                continuation = []
                for word in nxt.words:
                    if word.bold:
                        break
                    continuation.append(word.text)
                pairs[-1] = (pairs[-1][0], " ".join([pairs[-1][1], *continuation]).strip())
            for label, value in pairs:
                if label in allowed and value:
                    self.summary[label] = value

    # -- requirement rows ---------------------------------------------------------------
    def add_icon_rows(
        self,
        block: Block,
        icons: list[Icon],
        label_lines: list[Line],
        content_lines: list[Line],
        bbox: tuple[float, ...],
        page_no: int,
    ) -> None:
        centers = [i.center for i in icons]
        bounds = [(a + b) / 2 for a, b in zip(centers, centers[1:], strict=False)]

        def band_of(middle: float) -> int:
            return next((k for k, edge in enumerate(bounds) if middle < edge), len(icons) - 1)

        def band(line: Line) -> int:
            return band_of(line.top + TEXT_HALF_HEIGHT)

        # Multi-line content is vertically centred on its label, so assign whole paragraphs
        # (a line plus its indented continuation lines) by the paragraph's centre.
        content_band: dict[int, int] = {}
        for paragraph in _paragraphs(content_lines):
            middle = (paragraph[0].top + paragraph[-1].top) / 2 + TEXT_HALF_HEIGHT
            for line in paragraph:
                content_band[id(line)] = band_of(middle)

        for k, icon in enumerate(icons):
            status: IconStatus = icon.status
            if status == "unknown":
                region = (icon.x0, icon.top, icon.bottom)
                status = self.vision.classify_icon(self.pdf_path, page_no, region) or "unknown"
                if status == "unknown":
                    self.warnings.append(
                        f"page {page_no}: unrecognised icon color {icon.colors} at "
                        f"y={icon.top:.0f}; status left unknown (vision fallback unavailable)"
                    )
            self.add_row(
                block,
                page_no,
                icon.top,
                indent_level(icon, self.config),
                status,
                [ln for ln in label_lines if band(ln) == k],
                [ln for ln in content_lines if content_band[id(ln)] == k],
            )

    def add_row(
        self,
        block: Block,
        page_no: int,
        top: float,
        level: int | None,
        status: IconStatus | None,
        label_lines: list[Line],
        content_lines: list[Line],
    ) -> None:
        if not label_lines and not content_lines:
            return
        self.row_count += 1
        row = Row(
            row_id=f"r{self.row_count}",
            page=page_no,
            top=top,
            level=level,
            icon_status=status,
            label=" ".join(line.text for line in label_lines),
        )
        for line in content_lines:
            course = _course_line(line, block.columns) if block.columns else None
            if course is not None:
                row.courses.append(course)
            elif line.text.startswith("Satisfied by:") and row.courses:
                row.courses[-1].satisfied_by = line.text
            else:
                row.content.append(line.text)
        if level is not None:
            row.parent_id = next(
                (r.row_id for r in reversed(block.rows) if r.level is not None and r.level < level),
                None,
            )
        block.rows.append(row)


def _paragraphs(lines: list[Line]) -> list[list[Line]]:
    """Group a line with the following lines that are indented further (continuations)."""
    paragraphs: list[list[Line]] = []
    for line in lines:
        if paragraphs and line.x0 > paragraphs[-1][0].x0 + 2:
            paragraphs[-1].append(line)
        else:
            paragraphs.append([line])
    return paragraphs


def _label_value_pairs(line: Line) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    label: list[str] = []
    value: list[str] = []
    for word in line.words:
        if word.bold and abs(word.size - 8) < 0.5:
            if value:
                pairs.append((" ".join(label), " ".join(value)))
                label, value = [], []
            label.append(word.text)
        elif label:
            value.append(word.text)
    if label:
        pairs.append((" ".join(label), " ".join(value)))
    return pairs


def _course_line(line: Line, columns: Columns) -> CourseLine | None:
    cells: dict[str, list[str]] = {name: [] for name in COLUMN_NAMES}
    edges = [
        ("Course", columns.code),
        ("Title", columns.title),
        ("Grade", columns.grade),
        ("Credits", columns.credits),
        ("Term", columns.term),
        ("Repeated", columns.repeated),
    ]
    for word in line.words:
        name = next((n for n, x in reversed(edges) if word.x0 >= x - 1), None)
        if name is None:
            return None
        cells[name].append(word.text)
    code, term, credits = (" ".join(cells[n]) for n in ("Course", "Term", "Credits"))
    if not COURSE_CODE.match(code) or not TERM.match(term) or not cells["Grade"]:
        return None
    match = CREDITS.match(credits)
    return CourseLine(
        code=code,
        title=" ".join(cells["Title"]),
        grade=" ".join(cells["Grade"]),
        credits=float(match.group(1)) if match else None,
        term=term,
        repeated=" ".join(cells["Repeated"]),
        in_progress_marker=credits.startswith("("),
        source_text=line.text,
    )


def parse_layout(
    pdf_path: Path, config: SchoolConfig, vision: VisionFallback | None = None
) -> AuditLayout:
    parser = _Parser(config, vision or NoVisionFallback(), pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            parser.parse_page(page, index)
            if parser.done:
                break
    if not parser.done:
        parser.warnings.append("legend not found; the audit may be truncated")
    return AuditLayout(parser.summary, parser.blocks, parser.warnings)
