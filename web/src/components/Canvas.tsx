"use client";

import type { ReactNode } from "react";
import type { RequirementProgress, View } from "@/lib/api";
import { layout } from "@/lib/grid";
import { progressCells, progressState, requestStatus, splitTitle, type RequestStatus } from "@/lib/progress";
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
const planName = (i: number) => `Plan ${PLAN_NAMES[i] ?? i + 1}`;

function Heading({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
      <h2 className="font-marker text-2xl font-bold leading-none">{children}</h2>
      {note && <span className="text-pencil">{note}</span>}
    </div>
  );
}

/** A hand-drawn checkbox, ticked, crossed out, flagged or empty. */
function Box({ status }: { status: RequestStatus }) {
  return (
    <span className="sketch sketch-thin relative mt-0.5 inline-block h-5 w-5 shrink-0 bg-paper" aria-hidden>
      {status === "met" && (
        <Doodle kind="check" className="absolute -left-0.5 -top-2 h-7 w-7 text-pen-blue" strokeWidth={3} />
      )}
      {status === "missed" && (
        <Doodle kind="cross" className="absolute -left-1 -top-1 h-7 w-7 text-pen-red" strokeWidth={2.6} />
      )}
      {status === "clash" && (
        <span className="absolute inset-0 flex items-center justify-center font-marker text-xl font-bold leading-none text-pen-red">
          !
        </span>
      )}
    </span>
  );
}

const STATUS_NOTE: Record<RequestStatus, (plan: string) => string | null> = {
  met: () => null,
  missed: (plan) => `${plan} couldn't fit this one`,
  clash: () => "clashes with another must-have (see the pink note)",
  pending: () => null,
};

/** Everything here comes from the solver/audit view; no text is generated in the browser. */
export function Canvas({ view, index, busy, onPick, onDrop, onSend }: Props) {
  const schedule = view.schedules[index];
  const sections = schedule?.sections ?? [];
  const colorOf = layout(sections).colorOf;
  const plan = planName(index);
  const statuses = view.rules.map((r) => requestStatus(r.id, view, index));
  const met = statuses.filter((s) => s === "met").length;

  return (
    <div className="space-y-8 px-8 py-6">
      <section className="flex flex-wrap items-start gap-x-10 gap-y-4">
        <div className="min-w-0 flex-1">
          <Heading note={schedule && view.rules.length > 0 ? `${plan} meets ${met} of ${view.rules.length}` : null}>
            <span className="scribble-underline">My requests</span>
          </Heading>
          {view.rules.length === 0 ? (
            <p className="text-pencil">Nothing yet. Tell the assistant what you want, or flip open the catalog.</p>
          ) : (
            <ul className="grid gap-x-8 sm:grid-cols-2">
              {view.rules.map((r, i) => {
                const status = statuses[i]!;
                const note = STATUS_NOTE[status](plan);
                return (
                  <li key={r.id} className="flex items-start gap-2.5 py-1">
                    <Box status={status} />
                    <div className="min-w-0 flex-1 leading-snug" title={r.said ? `You said: “${r.said}”` : undefined}>
                      <span className={status === "missed" ? "text-pencil line-through decoration-pen-red" : ""}>
                        {r.text}
                      </span>
                      <span className="ml-1.5 text-sm text-pencil">
                        {r.default ? "(default)" : r.must ? "" : "(if possible)"}
                      </span>
                      {note && <div className="text-sm text-pen-red">{note}</div>}
                    </div>
                    {r.removable ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onDrop(r.id)}
                        className="px-1 font-marker text-lg leading-none text-pencil/60 hover:text-pen-red disabled:opacity-40"
                        aria-label={`Remove ${r.text}`}
                        title="Remove this request"
                      >
                        ✕
                      </button>
                    ) : (
                      <span className="px-1 text-sm text-pencil/70" title="Tell the assistant a different load to change it">
                        ✎
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
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
                  <span className="font-marker text-2xl font-bold leading-none">{planName(i)}</span>
                  <span className="text-xs text-pencil">
                    {s.credits} credits
                    {s.missed_rules.length > 0 && ` · misses ${s.missed_rules.length}`}
                  </span>
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
            {plan} · <span className="highlight">{schedule.credits} credits</span>
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
                  <div className="text-sm text-pencil">
                    {s.when} · {s.instructors.join(", ") || "Instructor TBA"}
                  </div>
                  {s.counts_toward.length > 0 && (
                    <div className="mt-2 border-t border-dashed border-ruled pt-1.5 text-sm">
                      <span className="text-pencil">counts toward</span>
                      <ul>
                        {s.counts_toward.map((t) => (
                          <li key={t} className="flex items-start gap-1.5 text-pen-blue" title={t}>
                            <Doodle kind="arrow" className="mt-0.5 h-3.5 w-3.5" strokeWidth={2.2} />
                            {splitTitle(t).name}
                          </li>
                        ))}
                      </ul>
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

      <Progress view={view} index={index} colorOf={colorOf} />
    </div>
  );
}

/** Degree progress for the plan on screen: what it adds to each open requirement, as
 * hand-drawn bars filled in each course's color. */
function Progress({ view, index, colorOf }: { view: View; index: number; colorOf: (course: string) => number }) {
  const schedule = view.schedules[index];
  const plan = planName(index);
  const creditsOf = (course: string) => schedule?.sections.find((s) => s.course === course)?.credits ?? 0;
  const rows = schedule?.progress ?? [];
  const helped = rows.filter((p) => progressState(p) !== "none");
  const open = schedule ? rows.filter((p) => progressState(p) === "none") : view.requirements;

  return (
    <section className="sketch sketch-alt ruled max-w-5xl px-5 pb-4 pl-14 pt-3">
      <Heading note={schedule ? `with ${plan}` : "from your audit"}>Degree progress</Heading>

      {helped.length > 0 && (
        <>
          <h3 className="mt-2 font-marker text-xl font-bold text-pen-blue">{plan} helps with…</h3>
          <ul className="mt-1 space-y-3">
            {helped.map((p) => (
              <ProgressRow key={p.title} p={p} colorOf={colorOf} creditsOf={creditsOf} />
            ))}
          </ul>
        </>
      )}

      {open.length > 0 && (
        <>
          <h3 className="mt-5 font-marker text-xl font-bold text-pencil">
            {schedule ? `Still open after ${plan}` : "Still needed"}
          </h3>
          <ul className="grid gap-x-8 sm:grid-cols-2">
            {open.map((r) => {
              const { name, path } = splitTitle(r.title);
              return (
                <li key={r.title} className="flex h-7 items-center gap-2" title={r.title}>
                  <Box status="pending" />
                  <span className="truncate">
                    {name}
                    {path && <span className="text-sm text-pencil"> · {path}</span>}
                  </span>
                  {r.needed && r.unit ? (
                    <span className="ml-auto shrink-0 text-sm text-pencil">
                      {r.needed} {r.needed === 1 ? r.unit.slice(0, -1) : r.unit}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {helped.length > 0 && (
        <p className="mt-4 text-sm text-pencil">
          A course can show up under more than one requirement; your audit decides whether it may count twice.
        </p>
      )}
    </section>
  );
}

function ProgressRow({
  p,
  colorOf,
  creditsOf,
}: {
  p: RequirementProgress;
  colorOf: (course: string) => number;
  creditsOf: (course: string) => number;
}) {
  const { name, path } = splitTitle(p.title);
  const state = progressState(p);
  const cells = progressCells(p, creditsOf);
  const amount =
    state === "counts"
      ? `+${p.planned} ${p.unit ?? (p.planned === 1 ? "course" : "courses")}`
      : `${p.planned} of ${p.needed} ${p.unit ?? ""}`;

  return (
    <li title={p.title}>
      <div className="flex items-baseline gap-2">
        <Box status={state === "done" ? "met" : "pending"} />
        <span className="font-semibold">{name}</span>
        {path && <span className="truncate text-sm text-pencil">{path}</span>}
        <span
          className={`ml-auto shrink-0 font-marker text-lg font-bold ${state === "done" ? "text-pen-blue" : "text-pencil"}`}
        >
          {state === "done" ? "covered!" : amount}
        </span>
      </div>
      <div className="ml-7 mt-1 flex items-center gap-3">
        {cells && (
          // the wobbly outline sits on the outer box so the clipped inner fill can't cut it
          <div className="sketch sketch-thin h-6 min-w-0 flex-1 bg-paper p-[2px]">
            <div className="flex h-full overflow-hidden rounded-sm">
              {cells.map((cell, i) => (
              <div
                key={i}
                style={{ width: `${cell.width * 100}%` }}
                className={`flex items-center justify-center truncate px-1 text-xs ${
                  i < cells.length - 1 ? "border-r border-dashed border-ink/40" : ""
                } ${cell.course ? `hatch ${courseStyle(colorOf(cell.course))}` : ""}`}
              >
                  {cell.course}
                </div>
              ))}
            </div>
          </div>
        )}
        {!cells && (
          <div className="flex flex-wrap gap-2 text-sm">
            {p.courses.map((c) => (
              <span key={c} className={`hatch sketch sketch-thin px-2 ${courseStyle(colorOf(c))}`}>
                {c}
              </span>
            ))}
          </div>
        )}
      </div>
    </li>
  );
}
