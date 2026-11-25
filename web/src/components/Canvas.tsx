"use client";

import type { View } from "@/lib/api";
import { layout } from "@/lib/grid";
import { courseDoodle, courseStyle, courseTilt, Doodle } from "./palette";
import { WeekGrid } from "./WeekGrid";

interface Props {
  view: View;
  index: number; // which schedule is shown
  busy: boolean;
  onPick: (index: number) => void;
  onDrop: (ruleId: string) => void;
  onSend: (text: string) => void;
}

const PLAN_NAMES = "ABCDEFGHIJ";

function Heading({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-2 font-marker text-2xl font-bold leading-none">{children}</h2>;
}

/** Everything here comes from the solver/audit view; no text is generated in the browser. */
export function Canvas({ view, index, busy, onPick, onDrop, onSend }: Props) {
  const schedule = view.schedules[index];
  const sections = schedule?.sections ?? [];
  const colorOf = layout(sections).colorOf;

  return (
    <div className="space-y-7 px-8 py-6">
      <section className="flex flex-wrap items-start gap-x-10 gap-y-4">
        <div className="min-w-0 flex-1">
          <Heading>
            <span className="scribble-underline">Wish list</span>
          </Heading>
          {view.rules.length === 0 ? (
            <p className="text-pencil">Nothing yet. Tell the assistant what you want, or flip open the catalog.</p>
          ) : (
            <div className="flex flex-wrap gap-2.5">
              {view.rules.map((r, i) => (
                <span
                  key={r.id}
                  title={r.said ? `You said: “${r.said}”` : "System default"}
                  className={`sketch sketch-thin inline-flex items-center gap-1 bg-paper py-0.5 pl-3 pr-1.5 ${
                    r.must ? "" : "sketch-dashed"
                  } ${i % 2 ? "sketch-alt" : ""}`}
                >
                  <Doodle kind={r.must ? "check" : "squiggle"} className="h-3.5 w-3.5 text-pen-blue" strokeWidth={2.4} />
                  <span>
                    {r.text}
                    {!r.must && <span className="ml-1 text-pencil">(if possible)</span>}
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onDrop(r.id)}
                    className="ml-1 px-1 font-marker text-xl leading-none text-pencil hover:text-pen-red disabled:opacity-40"
                    aria-label={`Remove ${r.text}`}
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {view.schedules.length > 0 && (
          <div>
            <Heading>Pick a plan</Heading>
            <div className="flex gap-3">
              {view.schedules.map((s, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => onPick(i)}
                  className={`sketch flex flex-col items-center px-3.5 pb-1 pt-0.5 transition-transform hover:-rotate-2 ${
                    i % 2 ? "sketch-alt" : ""
                  } ${i === index ? "bg-hl-yellow" : "bg-paper"}`}
                >
                  <span className="font-marker text-2xl font-bold leading-none">Plan {PLAN_NAMES[i] ?? i + 1}</span>
                  <span className="text-xs text-pencil">{s.credits} credits</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {view.status === "infeasible" && (
        <section
          className="sketch tape relative max-w-3xl bg-hl-pink px-6 pb-4 pt-5 shadow-[3px_4px_0_rgba(39,48,74,0.12)]"
          style={{ transform: "rotate(-0.6deg)" }}
        >
          <p className="font-marker text-2xl font-bold leading-none text-pen-red">Uh oh, these can&apos;t all fit!</p>
          <ul className="mt-2 space-y-0.5">
            {view.conflict.map((c) => (
              <li key={c} className="flex items-center gap-2">
                <Doodle kind="bolt" className="h-4 w-4 text-pen-red" /> {c}
              </li>
            ))}
          </ul>
          {view.why.length > 0 && <p className="mt-2 text-pencil">Why: {view.why.join("; ")}.</p>}
          <div className="mt-3 flex flex-wrap gap-2.5">
            {view.fixes.map((f) => (
              <button
                key={f.number}
                type="button"
                disabled={busy}
                onClick={() => onSend(String(f.number))}
                className="sketch sketch-thin bg-paper px-3 py-0.5 hover:bg-hl-yellow disabled:opacity-40"
              >
                drop “{f.text}” → {f.unlocks >= 5 ? "5+" : f.unlocks} schedules
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="relative">
        <WeekGrid sections={sections} />
        {!schedule && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div
              className="sketch tape relative bg-hl-yellow px-7 py-4 text-center shadow-[3px_4px_0_rgba(39,48,74,0.12)]"
              style={{ transform: "rotate(2deg)" }}
            >
              <p className="font-marker text-3xl font-bold leading-none">Nothing planned yet!</p>
              <p className="mt-1 text-pencil">
                {view.status === "infeasible" ? "Pick a fix on the pink note ↑" : "Ask the assistant to build one →"}
              </p>
            </div>
          </div>
        )}
      </section>

      {schedule && (
        <section>
          <Heading>
            Plan {PLAN_NAMES[index] ?? index + 1} · <span className="highlight">{schedule.credits} credits</span>
          </Heading>
          <div className="mt-4 grid gap-6 sm:grid-cols-2 2xl:grid-cols-3">
            {sections.map((s) => {
              const c = colorOf(s.course);
              return (
                <article
                  key={s.id}
                  className="sketch tape relative bg-paper px-4 pb-3 pt-4 shadow-[3px_4px_0_rgba(39,48,74,0.10)]"
                  style={{ transform: courseTilt(c + 3) }}
                >
                  <div className="flex items-center gap-2">
                    <span className={`flex h-7 w-7 items-center justify-center rounded-full ${courseStyle(c)}`}>
                      <Doodle kind={courseDoodle(c)} className="h-4 w-4" />
                    </span>
                    <span className="font-marker text-xl font-bold leading-none">{s.id}</span>
                    <span className="ml-auto text-sm text-pencil">{s.credits} cr</span>
                  </div>
                  <div className="mt-1">{s.title}</div>
                  <div className="text-sm text-pencil">{s.when}</div>
                  <div className="text-sm text-pencil">{s.instructors.join(", ") || "Instructor TBA"}</div>
                  {s.counts_toward.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5 text-sm">
                      {s.counts_toward.map((t) => (
                        <span key={t} className="highlight px-1">
                          ✓ {t}
                        </span>
                      ))}
                    </div>
                  )}
                  {s.warnings.map((w) => (
                    <div key={w} className="mt-1 text-sm text-pen-red">
                      ! {w}
                    </div>
                  ))}
                </article>
              );
            })}
          </div>
        </section>
      )}

      <section className="sketch sketch-alt ruled max-w-4xl px-5 pb-3 pl-14 pt-3">
        <Heading>To do before graduation</Heading>
        <ul className="grid gap-x-8 sm:grid-cols-2">
          {view.requirements.map((r) => (
            <li key={r.title} className="flex h-7 items-center gap-2">
              <span className="sketch sketch-thin h-4 w-4 shrink-0" aria-hidden />
              <span className="truncate">{r.title}</span>
              {r.needed && r.unit ? (
                <span className="ml-auto shrink-0 font-marker text-lg font-bold text-pen-red">
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
