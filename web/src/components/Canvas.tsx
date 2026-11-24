"use client";

import { useState } from "react";
import type { View } from "@/lib/api";
import { WeekGrid } from "./WeekGrid";

interface Props {
  view: View;
  busy: boolean;
  onDrop: (ruleId: string) => void;
  onSend: (text: string) => void;
}

/** Everything here comes from the solver/audit view; no text is generated in the browser. */
export function Canvas({ view, busy, onDrop, onSend }: Props) {
  const [picked, setPicked] = useState(0);
  const index = Math.min(picked, Math.max(view.schedules.length - 1, 0));
  const schedule = view.schedules[index];

  return (
    <div className="space-y-5">
      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Working with</h2>
        {view.rules.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing yet. Tell me what you want.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {view.rules.map((r) => (
              <span
                key={r.id}
                title={r.said ? `You said: “${r.said}”` : "System default"}
                className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs ${
                  r.must ? "border-slate-400 bg-white" : "border-dashed border-slate-400 bg-slate-50"
                }`}
              >
                {r.text}
                {!r.must && <span className="text-slate-400">(if possible)</span>}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDrop(r.id)}
                  className="ml-1 text-slate-400 hover:text-red-600 disabled:opacity-40"
                  aria-label={`Remove ${r.text}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </section>

      {view.status === "infeasible" && (
        <section className="rounded border border-red-200 bg-red-50 p-3 text-sm">
          <p className="font-medium text-red-800">These can&apos;t all hold at once:</p>
          <ul className="ml-4 list-disc text-red-800">
            {view.conflict.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          {view.why.length > 0 && <p className="mt-1 text-red-800">Why: {view.why.join("; ")}.</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            {view.fixes.map((f) => (
              <button
                key={f.number}
                type="button"
                disabled={busy}
                onClick={() => onSend(String(f.number))}
                className="rounded border border-red-300 bg-white px-2 py-1 text-xs hover:bg-red-100 disabled:opacity-40"
              >
                Drop “{f.text}” → {f.unlocks >= 5 ? "5+" : f.unlocks} schedules
              </button>
            ))}
          </div>
        </section>
      )}

      {schedule && (
        <section>
          <div className="mb-2 flex items-center gap-2">
            {view.schedules.map((s, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setPicked(i)}
                className={`rounded px-3 py-1 text-xs ${
                  i === index ? "bg-slate-800 text-white" : "bg-slate-100 hover:bg-slate-200"
                }`}
              >
                Schedule {i + 1} · {s.credits} cr
              </button>
            ))}
          </div>
          <WeekGrid sections={schedule.sections} />
          <table className="mt-3 w-full text-left text-xs">
            <tbody>
              {schedule.sections.map((s) => (
                <tr key={s.id} className="border-t border-slate-100 align-top">
                  <td className="py-1 pr-2 font-medium">{s.id}</td>
                  <td className="py-1 pr-2">
                    {s.title} ({s.credits} cr)
                    <div className="text-slate-500">
                      {s.when} · {s.instructors.join(", ") || "instructor TBA"}
                    </div>
                    {s.warnings.map((w) => (
                      <div key={w} className="text-amber-700">
                        ⚠ {w}
                      </div>
                    ))}
                  </td>
                  <td className="py-1 text-slate-600">
                    {s.counts_toward.length ? s.counts_toward.join("; ") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section>
        <h2 className="mb-1 text-sm font-semibold text-slate-700">Still needed (from your audit)</h2>
        <ul className="space-y-0.5 text-xs text-slate-700">
          {view.requirements.map((r) => (
            <li key={r.title}>
              {r.title}
              {r.needed && r.unit ? (
                <span className="text-slate-500">
                  {" "}
                  — {r.needed} {r.needed === 1 ? r.unit.slice(0, -1) : r.unit}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
