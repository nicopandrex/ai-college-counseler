"""Status icons: DegreeWorks draws them as vector curves in the left margin.

Each icon is several stacked curves (e.g. the incomplete icon is a white-filled disc under
a red ring), so curves are grouped into icons before classification. Neutral colors
(white/black) never decide a status; an unrecognised color yields "unknown".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from planner_ingest.config import IconStatus, SchoolConfig


@dataclass(frozen=True)
class Icon:
    x0: float
    top: float
    bottom: float
    status: IconStatus
    colors: tuple[tuple[float, ...], ...]

    @property
    def center(self) -> float:
        return (self.top + self.bottom) / 2


def _painted_colors(curve: Mapping[str, Any]) -> list[tuple[str, tuple[float, ...]]]:
    painted = []
    if curve.get("fill") and curve.get("non_stroking_color") is not None:
        painted.append(("fill", tuple(curve["non_stroking_color"])))
    if curve.get("stroke") and curve.get("stroking_color") is not None:
        painted.append(("stroke", tuple(curve["stroking_color"])))
    return painted


def _close(a: tuple[float, ...], b: tuple[float, ...], tolerance: float) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b, strict=True))


def _group(curves: list[Mapping[str, Any]], gap: float = 1.5) -> list[list[Mapping[str, Any]]]:
    """Group curves whose bounding boxes overlap (one icon = several concentric curves)."""
    groups: list[list[Mapping[str, Any]]] = []
    for curve in sorted(curves, key=lambda c: (c["top"], c["x0"])):
        for group in groups:
            if any(
                curve["x0"] <= g["x1"] + gap
                and g["x0"] <= curve["x1"] + gap
                and curve["top"] <= g["bottom"] + gap
                and g["top"] <= curve["bottom"] + gap
                for g in group
            ):
                group.append(curve)
                break
        else:
            groups.append([curve])
    return groups


def classify(group: list[Mapping[str, Any]], config: SchoolConfig) -> Icon | None:
    tol = config.color_tolerance
    statuses: set[IconStatus] = set()
    colors: list[tuple[float, ...]] = []
    unknown = False
    for curve in group:
        for paint, color in _painted_colors(curve):
            if any(_close(color, n, tol) for n in config.neutral_colors):
                continue
            colors.append(color)
            match = next(
                (c for c in config.icon_colors if c.paint == paint and _close(color, c.rgb, tol)),
                None,
            )
            if match is None:
                unknown = True
            else:
                statuses.add(match.status)
    if not colors:
        return None  # purely neutral shapes are not status icons
    status: IconStatus = statuses.pop() if len(statuses) == 1 and not unknown else "unknown"
    return Icon(
        x0=min(c["x0"] for c in group),
        top=min(c["top"] for c in group),
        bottom=max(c["bottom"] for c in group),
        status=status,
        colors=tuple(dict.fromkeys(colors)),
    )


def extract_icons(curves: Iterable[Mapping[str, Any]], config: SchoolConfig) -> list[Icon]:
    margin = [c for c in curves if c["x0"] < config.icon_margin_x]
    icons = (classify(group, config) for group in _group(margin))
    return sorted((i for i in icons if i is not None), key=lambda i: i.top)


def indent_level(icon: Icon, config: SchoolConfig) -> int:
    return max(0, round((icon.x0 - config.indent_base_x) / config.indent_step))
