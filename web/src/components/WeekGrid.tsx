import type { ScheduleSection } from "@/lib/api";
import { layout, WEEKDAYS } from "@/lib/grid";

const DAY_NAMES: Record<(typeof WEEKDAYS)[number], string> = {
  M: "Mon",
  T: "Tue",
  W: "Wed",
  R: "Thu",
  F: "Fri",
};
const COLORS = [
  "bg-sky-100 border-sky-400",
  "bg-amber-100 border-amber-400",
  "bg-emerald-100 border-emerald-400",
  "bg-rose-100 border-rose-400",
  "bg-violet-100 border-violet-400",
  "bg-lime-100 border-lime-400",
  "bg-orange-100 border-orange-400",
];
const HOUR_PX = 44;

export function WeekGrid({ sections }: { sections: ScheduleSection[] }) {
  const grid = layout(sections);
  const hours = Array.from({ length: grid.lastHour - grid.firstHour }, (_, i) => grid.firstHour + i);
  const height = hours.length * HOUR_PX;
  return (
    <div>
      <div className="flex text-xs">
        <div className="w-12 shrink-0" />
        {WEEKDAYS.map((d) => (
          <div key={d} className="flex-1 text-center font-medium text-slate-600">
            {DAY_NAMES[d]}
          </div>
        ))}
      </div>
      {grid.unplaced.length > 0 && (
        <div className="mb-2 flex items-start gap-2 border-y border-slate-200 py-2">
          <div className="w-12 shrink-0 pt-1 text-right text-[10px] leading-tight text-slate-500">
            online / no set time
          </div>
          <div className="flex flex-1 flex-wrap gap-2">
            {grid.unplaced.map((s) => (
              <div
                key={s.id}
                className={`rounded border-l-4 px-2 py-1 text-[11px] leading-tight ${COLORS[grid.colorOf(s.course) % COLORS.length]}`}
              >
                <div className="font-semibold">{s.id}</div>
                <div>{s.online ? "online, any time" : s.when}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex" style={{ height }}>
        <div className="relative w-12 shrink-0 text-[10px] text-slate-400">
          {hours.map((h, i) => (
            <div key={h} className="absolute right-1" style={{ top: i * HOUR_PX - 6 }}>
              {((h + 11) % 12) + 1}
              {h < 12 ? "am" : "pm"}
            </div>
          ))}
        </div>
        {WEEKDAYS.map((d, day) => (
          <div key={d} className="relative flex-1 border-l border-slate-200">
            {hours.map((h, i) => (
              <div
                key={h}
                className="absolute inset-x-0 border-t border-slate-100"
                style={{ top: i * HOUR_PX }}
              />
            ))}
            {grid.blocks
              .filter((b) => b.day === day)
              .map((b) => (
                <div
                  key={`${b.section}-${b.top}`}
                  className={`absolute inset-x-0.5 overflow-hidden rounded border-l-4 px-1 text-[11px] leading-tight ${COLORS[b.color % COLORS.length]}`}
                  style={{ top: `${b.top}%`, height: `${b.height}%` }}
                  title={`${b.section} ${b.title} ${b.label}`}
                >
                  <div className="font-semibold">{b.section}</div>
                  <div className="truncate">{b.label}</div>
                </div>
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}
