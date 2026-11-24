import { describe, expect, it } from "vitest";
import type { ScheduleSection } from "./api";
import { layout } from "./grid";

function section(id: string, days: string, start: number, end: number): ScheduleSection {
  return {
    id,
    course: id.split(" ").slice(0, 2).join(" "),
    title: id,
    credits: 3,
    instructors: [],
    when: "",
    online: false,
    meetings: days ? [{ days, start, end }] : [],
    counts_toward: [],
    warnings: [],
  };
}

describe("layout", () => {
  it("places each meeting day as a block, in proportion to the day", () => {
    const grid = layout([section("CS 3010 A", "MWF", 14 * 60 + 20, 15 * 60 + 10)]);
    expect(grid.firstHour).toBe(8);
    expect(grid.lastHour).toBe(17);
    expect(grid.blocks.map((b) => b.day)).toEqual([0, 2, 4]);
    expect(grid.blocks[0]?.label).toBe("2:20–3:10pm");
    expect(grid.blocks[0]?.top).toBeCloseTo((380 / 540) * 100);
  });

  it("labels a class that crosses noon with both halves", () => {
    const grid = layout([section("ECON 2020 B", "TR", 11 * 60 + 30, 12 * 60 + 45)]);
    expect(grid.blocks[0]?.label).toBe("11:30am–12:45pm");
  });

  it("stretches the grid for early and evening classes", () => {
    const grid = layout([
      section("CS 3990 A", "T", 18 * 60, 21 * 60),
      section("X 1000 A", "R", 7 * 60 + 30, 8 * 60 + 20),
    ]);
    expect(grid.firstHour).toBe(7);
    expect(grid.lastHour).toBe(21);
  });

  it("lists online and weekend sections under the grid instead", () => {
    const grid = layout([section("NFS 1073 OL1", "", 0, 0), section("ART 1000 A", "S", 600, 700)]);
    expect(grid.blocks).toEqual([]);
    expect(grid.colorOf("ART 1000")).toBe(0);
    expect(grid.unplaced.map((s) => s.id)).toEqual(["NFS 1073 OL1", "ART 1000 A"]);
  });
});
