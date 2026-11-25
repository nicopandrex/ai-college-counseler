import type { ScheduleSection } from "@/lib/api";
import { layout, WEEKDAYS } from "@/lib/grid";
import { courseDoodle, courseStyle, courseTilt, Doodle } from "./palette";

const DAY_NAMES: Record<(typeof WEEKDAYS)[number], string> = {
  M: "Monday",
  T: "Tuesday",
  W: "Wednesday",
  R: "Thursday",
  F: "Friday",
};
const HOUR_PX = 64;

function hourLabel(h: number): string {
  return `${((h + 11) % 12) + 1}${h < 12 ? "am" : "pm"}`;
}

/** The week as a hand-ruled planner page; classes are highlighter sticky notes. */
export function WeekGrid({ sections }: { sections: ScheduleSection[] }) {
  const grid = layout(sections);
  const hours = Array.from({ length: grid.lastHour - grid.firstHour }, (_, i) => grid.firstHour + i);
  return (
    <div className="sketch bg-paper px-2 pb-3 pt-1 shadow-[3px_4px_0_rgba(39,48,74,0.12)]">
      <div className="flex">
        <div className="w-14 shrink-0" />
        {WEEKDAYS.map((d) => (
          <div key={d} className="flex-1 px-2 pb-1 pt-2 text-center">
            <span className="font-marker text-2xl font-bold leading-none">{DAY_NAMES[d]}</span>
          </div>
        ))}
      </div>
      <svg viewBox="0 0 400 6" preserveAspectRatio="none" className="h-1.5 w-full text-ink" aria-hidden>
        <path d="M2 3 C 80 1, 160 5, 240 3 S 360 1, 398 3.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>

      {grid.unplaced.length > 0 && (
        <div className="flex items-center gap-3 border-b-2 border-dashed border-ruled py-3">
          <div className="w-14 shrink-0 text-right font-marker text-base leading-tight text-pencil">anytime</div>
          <div className="flex flex-1 flex-wrap gap-3">
            {grid.unplaced.map((s) => {
              const c = grid.colorOf(s.course);
              return (
                <div
                  key={s.id}
                  className={`sketch sketch-thin flex items-center gap-2 px-3 py-1 text-sm ${courseStyle(c)}`}
                  style={{ transform: courseTilt(c) }}
                >
                  <Doodle kind={courseDoodle(c)} className="h-4 w-4" />
                  <span className="font-marker text-lg font-bold leading-none">{s.id}</span>
                  <span className="text-pencil">{s.online ? "online, no set time" : s.when}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex" style={{ height: hours.length * HOUR_PX }}>
        <div className="relative w-14 shrink-0">
          {hours.map((h, i) => (
            <div
              key={h}
              className="absolute right-2 font-marker text-base font-semibold leading-none text-pencil"
              style={{ top: i * HOUR_PX + 2 }}
            >
              {hourLabel(h)}
            </div>
          ))}
        </div>
        {WEEKDAYS.map((d, day) => (
          <div key={d} className={`relative flex-1 ${day ? "border-l-2 border-dashed border-ruled" : ""}`}>
            {hours.map((h, i) => (
              <div key={h}>
                <div className="absolute inset-x-0 border-t border-ruled" style={{ top: i * HOUR_PX }} />
                <div
                  className="absolute inset-x-0 border-t border-dotted border-ruled/70"
                  style={{ top: i * HOUR_PX + HOUR_PX / 2 }}
                />
              </div>
            ))}
            {grid.blocks
              .filter((b) => b.day === day)
              .map((b) => (
                <div
                  key={`${b.section}-${b.top}`}
                  className={`sketch sketch-thin absolute inset-x-1.5 overflow-hidden px-2 py-1 shadow-[2px_3px_0_rgba(39,48,74,0.10)] ${courseStyle(b.color)}`}
                  style={{ top: `${b.top}%`, height: `${b.height}%`, transform: courseTilt(b.color) }}
                  title={`${b.section} · ${b.title} · ${b.label}`}
                >
                  <Doodle kind={courseDoodle(b.color)} className="absolute right-1.5 top-1.5 h-4 w-4" />
                  <div className="pr-5 font-marker text-lg font-bold leading-[1.05]">{b.section}</div>
                  <div className="truncate text-[13px] leading-tight">{b.title}</div>
                  <div className="text-[13px] leading-tight text-pencil">{b.label}</div>
                </div>
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}
