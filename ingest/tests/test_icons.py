from planner_ingest.config import load_school_config
from planner_ingest.icons import extract_icons, indent_level

UVM = load_school_config("uvm")
GREEN = (0, 0.502, 0.302)
RED = (0.8314, 0.1569, 0.1569)
BLUE = (0.1569, 0.4549, 0.7333)
WHITE = (1,)
BLACK = (0,)


def curve(x0, top, size, fill=None, stroke=None):
    return {
        "x0": x0,
        "x1": x0 + size,
        "top": top,
        "bottom": top + size,
        "fill": fill is not None,
        "non_stroking_color": fill if fill is not None else BLACK,
        "stroke": stroke is not None,
        "stroking_color": stroke if stroke is not None else BLACK,
    }


def complete_icon(x0, top):
    # three concentric green discs, as UVM renders them
    return [
        curve(x0, top, 8.4, fill=GREEN),
        curve(x0 + 0.8, top + 0.8, 6.8, fill=GREEN),
        curve(x0 + 1.8, top + 2.6, 4.8, fill=GREEN),
    ]


def incomplete_icon(x0, top):
    # white disc under a red ring: the white fill must not be read as "info"
    return [curve(x0, top, 7.2, fill=WHITE), curve(x0, top, 7.2, stroke=RED)]


def test_classifies_each_status_from_grouped_curves() -> None:
    curves = [
        *complete_icon(34.3, 62.5),
        *incomplete_icon(34.9, 101.7),
        *[curve(28.5, 356.0, 8.4, fill=BLUE), curve(29.3, 356.8, 6.8, fill=BLUE)],
    ]
    icons = extract_icons(curves, UVM)
    assert [i.status for i in icons] == ["complete", "incomplete", "in_progress"]


def test_white_fill_alone_is_not_an_icon() -> None:
    assert extract_icons([curve(30, 10, 7, fill=WHITE)], UVM) == []


def test_unknown_color_is_unknown_not_guessed() -> None:
    icons = extract_icons([curve(30, 10, 7, fill=(0.5, 0.1, 0.9))], UVM)
    assert [i.status for i in icons] == ["unknown"]


def test_red_as_fill_does_not_match_stroke_only_entry() -> None:
    icons = extract_icons([curve(30, 10, 7, fill=RED)], UVM)
    assert [i.status for i in icons] == ["unknown"]


def test_curves_outside_margin_are_ignored() -> None:
    assert extract_icons(complete_icon(306.0, 26.5), UVM) == []


def test_indent_levels_follow_icon_x() -> None:
    icons = extract_icons(
        [*complete_icon(28.5, 10), *complete_icon(34.3, 40), *incomplete_icon(41.0, 70)], UVM
    )
    assert [indent_level(i, UVM) for i in icons] == [0, 1, 2]
