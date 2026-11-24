import type { ScheduleSection } from "./api";

/** Weekly-grid layout for one schedule: pure, so it's tested without a browser. */
export const WEEKDAYS = ["M", "T", "W", "R", "F"] as const;

export interface Block {
  section: string; // section id, e.g. "CS 3010 A"
  title: string;
  day: number; // index into WEEKDAYS
  top: number; // % of the grid's height
  height: number;
  color: number; // stable per course within the schedule
  label: string; // "2:20–3:10pm"
}

export interface Grid {
  firstHour: number;
  lastHour: number; // exclusive
  blocks: Block[];
  unplaced: ScheduleSection[]; // online / arranged / weekend: listed under the grid
}

export function clock(minute: number): string {
  const hour = Math.floor(minute / 60);
  const mins = String(minute % 60).padStart(2, "0");
  return `${((hour + 11) % 12) + 1}:${mins}${hour < 12 ? "am" : "pm"}`;
}

function span(start: number, end: number): string {
  const [a, b] = [clock(start), clock(end)];
  return a.slice(-2) === b.slice(-2) ? `${a.slice(0, -2)}–${b}` : `${a}–${b}`;
}

export function layout(sections: ScheduleSection[]): Grid {
  const timed = sections.flatMap((s) =>
    s.meetings.flatMap((m) =>
      [...m.days]
        .map((d) => WEEKDAYS.indexOf(d as (typeof WEEKDAYS)[number]))
        .filter((day) => day >= 0)
        .map((day) => ({ s, m, day })),
    ),
  );
  const firstHour = Math.min(8, ...timed.map((t) => Math.floor(t.m.start / 60)));
  const lastHour = Math.max(17, ...timed.map((t) => Math.ceil(t.m.end / 60)));
  const minutes = (lastHour - firstHour) * 60;
  const courses = [...new Set(sections.map((s) => s.course))].sort();
  const blocks = timed.map(({ s, m, day }) => ({
    section: s.id,
    title: s.title,
    day,
    top: ((m.start - firstHour * 60) / minutes) * 100,
    height: ((m.end - m.start) / minutes) * 100,
    color: courses.indexOf(s.course),
    label: span(m.start, m.end),
  }));
  const placed = new Set(blocks.map((b) => b.section));
  return { firstHour, lastHour, blocks, unplaced: sections.filter((s) => !placed.has(s.id)) };
}
