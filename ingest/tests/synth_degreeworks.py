"""Synthetic DegreeWorks-style PDFs for tests.

Reproduces the geometry of UVM's DegreeWorks export (table row rules, left-margin vector
icons, label/content columns, per-block column headers) with an invented student, so tests
exercise the real parsing path without committing real student data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

PAGE_W, PAGE_H = 612.0, 792.0
TABLE_X0, TABLE_X1 = 28.346, 583.654
TABLE_TOP = 22.676
GREEN = (0.0, 0.502, 0.302)
RED = (0.8314, 0.1569, 0.1569)
BLUE = (0.1569, 0.4549, 0.7333)
MAIN_COLUMNS = {
    "Course": 222.7,
    "Title": 280.5,
    "Grade": 417.6,
    "Credits": 450.1,
    "Term": 482.6,
    "Repeated": 548.5,
}
WIDE_COLUMNS = {
    "Course": 28.3,
    "Title": 117.2,
    "Grade": 344.9,
    "Credits": 389.3,
    "Term": 433.7,
    "Repeated": 539.2,
}
DATA_X = {"code": 224.7, "title": 282.1, "grade": 430.0, "credits": 464.8, "term": 483.1}
WIDE_DATA_X = {"code": 28.3, "title": 117.2, "grade": 344.9, "credits": 389.3, "term": 433.7}


@dataclass(frozen=True)
class Text:
    x: float
    dy: float  # offset of the text top below the cell top
    text: str
    font: str = "Helvetica"
    size: float = 8.0


@dataclass(frozen=True)
class IconMark:
    status: str  # complete | incomplete | in_progress | custom
    level: int
    dy: float
    rgb: tuple[float, float, float] | None = None  # for "custom"


@dataclass
class Cell:
    height: float
    texts: list[Text] = field(default_factory=list)
    icons: list[IconMark] = field(default_factory=list)


@dataclass(frozen=True)
class Course:
    code: str
    title: str
    grade: str
    credits: str
    term: str


def course_texts(course: Course, dy: float, wide: bool = False) -> list[Text]:
    x = WIDE_DATA_X if wide else DATA_X
    return [
        Text(x["code"], dy, course.code),
        Text(x["title"], dy, course.title),
        Text(x["grade"], dy, course.grade),
        Text(
            x["credits"] - (2.6 if course.credits.startswith("(") and not wide else 0),
            dy,
            course.credits,
        ),
        Text(x["term"], dy, course.term),
    ]


def summary_cell(fields: list[list[tuple[str, str]]]) -> Cell:
    """Rows of bold `Label` + regular value pairs laid out left to right."""
    cell = Cell(height=20.0 * len(fields) + 10)
    for r, row in enumerate(fields):
        x = 28.3
        for label, value in row:
            dy = 8 + 20 * r
            cell.texts.append(Text(x, dy, label, "Helvetica-Bold"))
            x += 6 + 4.6 * len(label)
            cell.texts.append(Text(x, dy, value))
            x += 6 + 4.2 * len(value)
    return cell


def block_header(title: str, status: str | None, info: str, wide: bool = False) -> Cell:
    cell = Cell(height=70.0)
    cell.texts.append(Text(28.3, 12, title, "Helvetica-Bold", 14))
    if status:
        cell.texts.append(Text(28.3, 32, status))
    cell.texts.append(Text(28.3, 44, info))
    for name, x in (WIDE_COLUMNS if wide else MAIN_COLUMNS).items():
        cell.texts.append(Text(x, 60, name, "Helvetica-Bold", 6))
    return cell


def requirement(
    level: int,
    status: str,
    label: str,
    still_needed: list[str] | None = None,
    courses: list[Course] | None = None,
    content: list[str] | None = None,
) -> Cell:
    """One requirement row: icon + label, then still-needed text, course lines, other text."""
    texts = [Text(40.0 + 6 * level, 12, label)]
    dy = 12.0
    for i, line in enumerate(still_needed or []):
        texts.append(Text(225.0 if i == 0 else 278.0, dy, line))
        dy += 9.5
    for course in courses or []:
        texts.extend(course_texts(course, dy))
        dy += 15
    for line in content or []:
        texts.append(Text(289.0, dy, line))
        dy += 12
    return Cell(height=max(28.5, dy + 12), texts=texts, icons=[IconMark(status, level, 10.5)])


def course_list_cell(courses: list[Course]) -> Cell:
    texts = [t for i, c in enumerate(courses) for t in course_texts(c, 8 + 17 * i, wide=True)]
    return Cell(height=17.0 * len(courses) + 10, texts=texts)


def legend_cell() -> Cell:
    return Cell(
        height=40.0,
        texts=[Text(28.3, 8, "Legend", "Helvetica-Bold", 10), Text(56.0, 28, "Complete")],
    )


def _draw_icon(canvas: Canvas, icon: IconMark, cell_top: float) -> None:
    x0 = 28.5 + 6 * icon.level
    top = cell_top + icon.dy
    cx, cy = x0 + 4.2, PAGE_H - (top + 4.2)
    if icon.status == "incomplete":
        canvas.setFillGray(1)
        canvas.setStrokeColorRGB(*RED)
        canvas.circle(cx, cy, 3.6, stroke=0, fill=1)
        canvas.circle(cx, cy, 3.6, stroke=1, fill=0)
        return
    rgb = {"complete": GREEN, "in_progress": BLUE}.get(icon.status, icon.rgb)
    assert rgb is not None
    canvas.setFillColorRGB(*rgb)
    for radius in (4.2, 3.4, 2.4):
        canvas.circle(cx, cy, radius, stroke=0, fill=1)


def build_pdf(path: Path, pages: list[list[Cell]]) -> Path:
    canvas = Canvas(str(path), pagesize=(PAGE_W, PAGE_H))
    for cells in pages:
        bottom = TABLE_TOP + sum(c.height for c in cells)
        canvas.setFillGray(1)
        canvas.rect(TABLE_X0, PAGE_H - bottom, TABLE_X1 - TABLE_X0, bottom - TABLE_TOP, 0, 1)
        top = TABLE_TOP
        for cell in cells:
            for text in cell.texts:
                canvas.setFillGray(0)
                canvas.setFont(text.font, text.size)
                # reportlab draws from the baseline; pdfplumber reports the glyph-box top
                canvas.drawString(text.x, PAGE_H - (top + text.dy) - text.size * 0.77, text.text)
            for icon in cell.icons:
                _draw_icon(canvas, icon, top)
            top += cell.height
            canvas.setStrokeGray(0.9333)
            canvas.setLineWidth(1)
            canvas.line(TABLE_X0, PAGE_H - top, TABLE_X1, PAGE_H - top)
        canvas.showPage()
    canvas.save()
    return path


def sample_audit(path: Path) -> Path:
    """A two-page synthetic audit covering the patterns seen in real UVM audits."""
    taken = Course("CS 1210", "Intro Programming", "A", "3", "Fall 2024")
    calc = Course("MATH 1234", "Calculus I", "B+", "4", "Fall 2024")
    ip = Course("CS 2500", "Intro to Databases", "IP", "(3)", "Fall 2026")
    transfer = Course("ARTS 1XXX", "1000 Level ARTS", "TR", "1", "Summer 2025")
    page1 = [
        Cell(height=30.0, texts=[Text(56.7, 8, "University of Vermont")]),
        summary_cell(
            [
                [("Student name", "Example, Alex"), ("Program", "Bachelor of Science")],
                [("Level", "Undergraduate"), ("Majors", "Computer Science"), ("NetID", "aexampl")],
            ]
        ),
        block_header(
            "Bachelor of Science, TEST",
            "INCOMPLETE",
            "Credits required: 120 Credits applied: 10 Catalog year: 2024-2025",
        ),
        Cell(
            height=60.0,
            texts=[
                Text(225.0, 6, "Still needed: 120 credits are required. You currently have 10"),
                Text(278.0, 15.5, "(including in-progress courses); you need 110 more credits."),
                Text(40.0, 12, "Total Credit Requirement"),
                Text(40.0, 40, "You meet the minimum Overall GPA requirement."),
            ],
            icons=[IconMark("incomplete", 0, 10.5), IconMark("complete", 0, 38.5)],
        ),
        requirement(0, "complete", "Computer Programming I", courses=[taken]),
        requirement(0, "in_progress", "INTERMEDIATE LEVEL. 3 additional credits:", courses=[ip]),
        requirement(
            0, "incomplete", "Senior Seminar", still_needed=["Still needed: 1 Class in CS 3920"]
        ),
        requirement(
            0,
            "incomplete",
            "CHOOSE ONE TRACK:",
            still_needed=["Still needed: Choose from 1 of the following:"],
        ),
        requirement(
            1, "incomplete", "TRACK 1", content=["You must complete all of the following:"]
        ),
        requirement(2, "complete", "Calculus I", courses=[calc]),
        requirement(2, "incomplete", "Calculus II", content=["4 Credits in MATH 1248"]),
    ]
    page2 = [
        block_header("Electives", None, "Credits applied: 1 Classes applied: 1", wide=True),
        course_list_cell([transfer]),
        block_header("In-progress", None, "Credits applied: 3 Classes applied: 1", wide=True),
        course_list_cell([ip]),
        legend_cell(),
    ]
    return build_pdf(path, [page1, page2])
