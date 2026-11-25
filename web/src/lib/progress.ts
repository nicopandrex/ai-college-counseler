import type { RequirementProgress, View } from "./api";

/** How one request fares in the plan on screen (from the solver's view, never guessed). */
export type RequestStatus = "met" | "missed" | "clash" | "pending";

export function requestStatus(ruleId: string, view: View, plan: number): RequestStatus {
  if (view.status === "infeasible") return view.conflict_ids.includes(ruleId) ? "clash" : "pending";
  const schedule = view.schedules[plan];
  if (!schedule) return "pending";
  return schedule.missed_rules.includes(ruleId) ? "missed" : "met";
}

/** How far this plan gets an open requirement. "counts": the audit gives no amount needed. */
export type ProgressState = "done" | "partial" | "counts" | "none";

export function progressState(p: RequirementProgress): ProgressState {
  if (p.courses.length === 0) return "none";
  if (p.needed === null) return "counts";
  return p.planned >= p.needed ? "done" : "partial";
}

export interface Cell {
  course: string | null; // null: still empty
  width: number; // share of the bar, 0..1
}

const MAX_CELLS = 10;

/** Progress-bar cells: one per course needed, or credit-sized pieces. Null when the audit
 * doesn't say how much is needed. */
export function progressCells(p: RequirementProgress, creditsOf: (course: string) => number): Cell[] | null {
  if (p.needed === null || p.needed <= 0 || p.unit === null) return null;
  if (p.unit === "courses") {
    const n = Math.min(Math.ceil(p.needed), MAX_CELLS);
    return Array.from({ length: n }, (_, i) => ({ course: p.courses[i] ?? null, width: 1 / n }));
  }
  const cells: Cell[] = [];
  let left = 1;
  for (const course of p.courses) {
    const width = Math.min(creditsOf(course) / p.needed, left);
    if (width <= 0) break;
    cells.push({ course, width });
    left -= width;
  }
  if (left > 1e-9) cells.push({ course: null, width: left });
  return cells;
}

/** "Liberal Arts › Social Sciences (S1)" -> the last part, and the path above it. */
export function splitTitle(title: string): { name: string; path: string } {
  const parts = title.split(" › ");
  return { name: parts[parts.length - 1]!, path: parts.slice(0, -1).join(" › ") };
}
