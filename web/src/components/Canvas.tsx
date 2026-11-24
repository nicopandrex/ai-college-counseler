"use client";

import type { View } from "@/lib/api";
import { layout } from "@/lib/grid";
import { courseShape, courseStyle, Shape } from "./palette";
import { WeekGrid } from "./WeekGrid";

interface Props {
  view: View;
  index: number; // which schedule is shown
  busy: boolean;
  onPick: (index: number) => void;
  onDrop: (ruleId: string) => void;
  onSend: (text: string) => void;
}

/** Everything here comes from the solver/audit view; no text is generated in the browser. */
export function Canvas({ view, index, busy, onPick, onDrop, onSend }: Props) {
  const schedule = view.schedules[index];
  const sections = schedule?.sections ?? [];
  const colorOf = layout(sections).colorOf;

  return (
    <div className="space-y-6 p-6">
      <section className="flex flex-wrap items-start gap-x-8 gap-y-4">
        <div className="min-w-0 flex-1">
          <h2 className="label mb-2">Working with</h2>
          {view.rules.length === 0 ? (
            <p className="text-sm text-ink/60">Nothing yet. Tell the assistant what you want, or open the catalog.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {view.rules.map((r) => (
                <span
                  key={r.id}
                  title={r.said ? `You said: “${r.said}”` : "System default"}
                  className={`group inline-flex items-center border-2 border-ink text-xs ${
                    r.must ? "bg-white" : "border-dashed bg-transparent"
                  }`}
                >
                  <span className="px-2.5 py-1">
                    {r.text}
                    {!r.must && <span className="ml-1 text-ink/50">if possible</span>}
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onDrop(r.id)}
                    className="self-stretch border-l-2 border-ink px-2 font-bold hover:bg-red hover:text-white disabled:opacity-40"
                    aria-label={`Remove ${r.text}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {view.schedules.length > 0 && (
          <div>
            <h2 className="label mb-2">Options</h2>
            <div className="flex border-2 border-ink">
              {view.schedules.map((s, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => onPick(i)}
                  className={`flex flex-col items-start px-3 py-1 text-left ${i ? "border-l-2 border-ink" : ""} ${
                    i === index ? "bg-ink text-paper" : "bg-white hover:bg-yellow"
                  }`}
                >
                  <span className="text-lg font-bold leading-none tabular-nums">{String(i + 1).padStart(2, "0")}</span>
                  <span className="text-[10px] uppercase tracking-widest">{s.credits} cr</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {view.status === "infeasible" && (
        <section className="flex border-2 border-ink bg-white">
          <div className="w-3 shrink-0 bg-red" />
          <div className="p-4 text-sm">
            <p className="label text-red">These can&apos;t all hold at once</p>
            <ul className="mt-2 space-y-1">
              {view.conflict.map((c) => (
                <li key={c} className="flex items-center gap-2">
                  <Shape kind="square" className="h-1.5 w-1.5" /> {c}
                </li>
              ))}
            </ul>
            {view.why.length > 0 && <p className="mt-2 text-ink/70">Why: {view.why.join("; ")}.</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              {view.fixes.map((f) => (
                <button
                  key={f.number}
                  type="button"
                  disabled={busy}
                  onClick={() => onSend(String(f.number))}
                  className="border-2 border-ink px-3 py-1 text-xs font-medium hover:bg-ink hover:text-paper disabled:opacity-40"
                >
                  Drop “{f.text}” → {f.unlocks >= 5 ? "5+" : f.unlocks} schedules
                </button>
              ))}
            </div>
          </div>
        </section>
      )}

      <section className="relative">
        <WeekGrid sections={sections} />
        {!schedule && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="border-2 border-ink bg-paper px-6 py-4 text-center">
              <p className="label">No schedule yet</p>
              <p className="mt-1 text-sm text-ink/70">
                {view.status === "infeasible" ? "Pick a fix above to see options." : "Ask the assistant to build one →"}
              </p>
            </div>
          </div>
        )}
      </section>

      {schedule && (
        <section>
          <h2 className="label mb-2">
            Schedule {String(index + 1).padStart(2, "0")} · {schedule.credits} credits
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
            {sections.map((s) => {
              const c = colorOf(s.course);
              return (
                <article key={s.id} className="flex border-2 border-ink bg-white">
                  <div className={`flex w-10 shrink-0 items-start justify-center pt-3 ${courseStyle(c)}`}>
                    <Shape kind={courseShape(c)} />
                  </div>
                  <div className="min-w-0 p-3 text-xs">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-bold">{s.id}</span>
                      <span className="text-ink/50">{s.credits} cr</span>
                    </div>
                    <div className="font-medium">{s.title}</div>
                    <div className="mt-1 text-ink/70">{s.when}</div>
                    <div className="text-ink/70">{s.instructors.join(", ") || "Instructor TBA"}</div>
                    {s.counts_toward.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {s.counts_toward.map((t) => (
                          <span key={t} className="bg-yellow px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                    {s.warnings.map((w) => (
                      <div key={w} className="mt-1 text-red">
                        ▲ {w}
                      </div>
                    ))}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      <section>
        <h2 className="label mb-2">Still needed · from your audit</h2>
        <ul className="grid gap-x-6 border-t-2 border-ink sm:grid-cols-2">
          {view.requirements.map((r) => (
            <li key={r.title} className="flex items-baseline justify-between gap-3 border-b border-rule py-1.5 text-xs">
              <span>{r.title}</span>
              {r.needed && r.unit ? (
                <span className="shrink-0 font-bold tabular-nums">
                  {r.needed} {r.needed === 1 ? r.unit.slice(0, -1) : r.unit}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
