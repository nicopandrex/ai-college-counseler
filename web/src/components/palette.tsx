/** One highlighter color, one doodle and one slight tilt per course, shared by the calendar,
 * cards and catalog, so a course looks the same everywhere. */
const STYLES = [
  "bg-hl-yellow",
  "bg-hl-pink",
  "bg-hl-blue",
  "bg-hl-green",
  "bg-hl-orange",
  "bg-hl-purple",
  "bg-hl-mint",
] as const;
const TILTS = [-1.1, 0.8, -0.5, 1.2, -0.9, 0.5, 1.4] as const;

const PATHS = {
  star: "M12 2.8l2.5 5.9 6.3.7-4.8 4.2 1.5 6.3-5.5-3.3-5.6 3.2 1.6-6.2L3.2 9.4l6.3-.6z",
  heart:
    "M12 20s-7-4.4-8.6-9C2.3 7.6 4.6 4.5 7.6 4.6c2 .1 3.4 1.4 4.4 3 1-1.6 2.4-2.9 4.4-3 3-.1 5.3 3 4.2 6.4C19 15.6 12 20 12 20z",
  bolt: "M13.5 2.5L5 13.5h6.2l-1.7 8L19 10h-6.3z",
  sun: "M12 8.4a3.6 3.6 0 1 1-.1 0M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1",
  spiral:
    "M12 12c0-1 1.5-1.2 2-.4.8 1.2-.4 2.9-2 2.9-2.2 0-3.4-2.4-2.5-4.3 1.2-2.6 4.8-3 6.7-1.1 2.4 2.4 1.5 6.6-1.7 7.9-3.8 1.6-8-1-8.6-5",
  circle: "M12 3.5c4.8-.3 8.7 3.4 8.5 8.4-.2 4.6-4 8.4-8.7 8.1C7 19.8 3.3 16 3.6 11.4 3.9 7 7.4 3.8 12 3.5c1.5 0 2.6.4 3.4.9",
  flower:
    "M12 9.5a2.5 2.5 0 1 1-.1 0M12 9.5C10 5 14 3 14.5 6.5M14.4 11c3.6-2.6 6.3.8 3 2.2M13.4 14.3c2.2 3.8-1.4 5.8-2.6 2.6M10.6 14.4c-3.6 2.6-6-.9-2.8-2.3M9.6 11c-2.3-3.8 1.4-5.6 2.4-1.5",
  arrow: "M3 15c4-7 10.5-9.2 17-5.8M15.5 5.2l4.6 4.2-5.4 2.4",
  check: "M4 13.5l4.6 4.8L20 5.5",
  cross: "M5.5 5c4.5 4.2 8.7 9 13.5 14M18.5 5.5C13.8 9.6 9.5 14 5 19",
  squiggle: "M2 12c2-4 4-4 6 0s4 4 6 0 4-4 6 0",
} as const;

export type DoodleKind = keyof typeof PATHS;
const COURSE_DOODLES: DoodleKind[] = ["star", "heart", "bolt", "sun", "spiral", "flower", "circle"];

const wrap = <T,>(list: readonly T[], i: number): T => list[((i % list.length) + list.length) % list.length]!;

export const courseStyle = (index: number): string => wrap(STYLES, index);
export const courseDoodle = (index: number): DoodleKind => wrap(COURSE_DOODLES, index);
export const courseTilt = (index: number): string => `rotate(${wrap(TILTS, index)}deg)`;

/** A pen doodle in the current text color. */
export function Doodle({
  kind,
  className = "h-4 w-4",
  strokeWidth = 1.8,
}: {
  kind: DoodleKind;
  className?: string;
  strokeWidth?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`inline-block shrink-0 ${className}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={PATHS[kind]} />
    </svg>
  );
}
