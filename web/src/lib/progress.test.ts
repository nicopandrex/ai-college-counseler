import { describe, expect, it } from "vitest";
import type { RequirementProgress, View } from "./api";
import { progressCells, progressState, requestStatus, splitTitle } from "./progress";

function req(over: Partial<RequirementProgress>): RequirementProgress {
  return { title: "R", needed: 2, unit: "courses", planned: 0, courses: [], ...over };
}

function view(over: Partial<View>): View {
  return {
    term: "2027SP",
    rules: [],
    status: "ok",
    schedules: [{ credits: 3, sections: [], missed_rules: ["c2"], progress: [] }],
    conflict_ids: [],
    conflict: [],
    why: [],
    fixes: [],
    questions: [],
    choices: [],
    requirements: [],
    facts: { credits_earned: null, credits_in_progress: null, standing: null, in_progress: [] },
    ...over,
  };
}

describe("requestStatus", () => {
  it("reads met and missed from the plan on screen", () => {
    expect(requestStatus("c1", view({}), 0)).toBe("met");
    expect(requestStatus("c2", view({}), 0)).toBe("missed");
  });

  it("marks the clashing requests when nothing fits, and the rest as pending", () => {
    const stuck = view({ status: "infeasible", schedules: [], conflict_ids: ["c1"] });
    expect(requestStatus("c1", stuck, 0)).toBe("clash");
    expect(requestStatus("c2", stuck, 0)).toBe("pending");
    expect(requestStatus("c1", view({ status: null, schedules: [] }), 0)).toBe("pending");
  });
});

describe("progress", () => {
  it("is done, partial, counts (no amount on the audit) or none", () => {
    expect(progressState(req({ planned: 2, courses: ["A 1", "B 1"] }))).toBe("done");
    expect(progressState(req({ planned: 1, courses: ["A 1"] }))).toBe("partial");
    expect(progressState(req({ needed: null, unit: null, planned: 1, courses: ["A 1"] }))).toBe("counts");
    expect(progressState(req({}))).toBe("none");
  });

  it("draws one cell per course needed", () => {
    expect(progressCells(req({ planned: 1, courses: ["A 1"] }), () => 3)).toEqual([
      { course: "A 1", width: 0.5 },
      { course: null, width: 0.5 },
    ]);
  });

  it("sizes credit pieces by the course's credits, capped at what's needed", () => {
    const cells = progressCells(req({ needed: 6, unit: "credits", planned: 4, courses: ["A 1", "B 1"] }), (c) =>
      c === "A 1" ? 1 : 3,
    );
    expect(cells?.map((c) => c.course)).toEqual(["A 1", "B 1", null]);
    expect(cells?.map((c) => c.width.toFixed(3))).toEqual(["0.167", "0.500", "0.333"]);
    expect(progressCells(req({ needed: null, unit: null }), () => 3)).toBeNull();
  });

  it("splits a requirement path from its name", () => {
    expect(splitTitle("Liberal Arts › Social Sciences (S1)")).toEqual({
      name: "Social Sciences (S1)",
      path: "Liberal Arts",
    });
    expect(splitTitle("Macroeconomics")).toEqual({ name: "Macroeconomics", path: "" });
  });
});
