import type { ScheduleSection } from "@/lib/api";
import { layout, WEEKDAYS } from "@/lib/grid";
import { courseShape, courseStyle, Shape } from "./palette";

const DAY_NAMES: Record<(typeof WEEKDAYS)[number], string> = {
  M: "Mon",
  T: "Tue",
  W: "Wed",
  R: "Thu",
  F: "Fri",
};
const HOUR_PX = 60;

function hourLabel(h: number): string {
  return `${((h + 11) % 12) + 1}${h < 12 ? "am" : "pm"}`;
}

export function WeekGrid({ sections }: { sections: ScheduleSection[] }) {
  const grid = layout(sections);
  const hours = Array.from({ length: grid.lastHour - grid.firstHour }, (_, i) => grid.firstHour + i);
  return (
    <div className="border-2 border-ink bg-white">
      <div className="flex border-b-2 border-ink">
        <div className="w-14 shrink-0 border-r-2 border-ink" />
        {WEEKDAYS.map((d, i) => (
          <div
            key={d}
            className={`flex-1 px-3 py-2 text-sm font-bold uppercase tracking-[0.2em] ${i ? "border-l border-rule" : ""}`}
          >
            {DAY_NAMES[d]}
          </div>
        ))}
      </div>

      {grid.unplaced.length > 0 && (
        <div className="flex border-b-2 border-ink">
          <div className="flex w-14 shrink-0 items-center justify-center border-r-2 border-ink">
            <span className="label -rotate-90 whitespace-nowrap text-[9px]">Any time</span>
          </div>
          <div className="flex flex-1 flex-wrap gap-2 p-2">
            {grid.unplaced.map((s) => {
              const c = grid.colorOf(s.course);
              return (
                <div key={s.id} className={`flex items-center gap-2 px-3 py-1.5 text-xs ${courseStyle(c)}`}>
                  <Shape kind={courseShape(c)} />
                  <span className="font-bold">{s.id}</span>
                  <span className="opacity-80">{s.online ? "online · no set time" : s.when}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex" style={{ height: hours.length * HOUR_PX }}>
        <div className="relative w-14 shrink-0 border-r-2 border-ink">
          {hours.map((h, i) => (
            <div
              key={h}
              className="absolute right-2 text-[10px] font-medium uppercase tabular-nums text-ink/60"
              style={{ top: i * HOUR_PX + 4 }}
            >
              {hourLabel(h)}
            </div>
          ))}
        </div>
        {WEEKDAYS.map((d, day) => (
          <div key={d} className={`relative flex-1 ${day ? "border-l border-rule" : ""}`}>
            {hours.map((h, i) => (
              <div
                key={h}
                className={`absolute inset-x-0 ${i ? "border-t border-rule" : ""}`}
                style={{ top: i * HOUR_PX }}
              />
            ))}
            {grid.blocks
              .filter((b) => b.day === day)
              .map((b) => (
                <div
                  key={`${b.section}-${b.top}`}
                  className={`absolute inset-x-1 overflow-hidden px-2 py-1.5 ${courseStyle(b.color)}`}
                  style={{ top: `${b.top}%`, height: `${b.height}%` }}
                  title={`${b.section} · ${b.title} · ${b.label}`}
                >
                  <Shape kind={courseShape(b.color)} className="absolute right-1.5 top-1.5 h-2 w-2 opacity-90" />
                  <div className="pr-3 text-xs font-bold leading-tight">{b.section}</div>
                  <div className="truncate text-[11px] leading-tight opacity-85">{b.title}</div>
                  <div className="text-[11px] tabular-nums leading-tight opacity-85">{b.label}</div>
                </div>
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}
