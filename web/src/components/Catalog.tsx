"use client";

import { useEffect, useRef, useState } from "react";
import { searchCatalog, type Catalog as Results, type CatalogCourse } from "@/lib/api";
import { Shape } from "./palette";

interface Props {
  session: string;
  open: boolean;
  busy: boolean;
  scheduled: ReadonlySet<string>; // course codes in the schedule on screen
  onClose: () => void;
  onAdd: (course: CatalogCourse) => void;
}

const STATUS: Record<CatalogCourse["status"], { text: string; tone: string } | null> = {
  open: null,
  taken: { text: "Taken", tone: "bg-ink/10 text-ink/60" },
  blocked: { text: "Can't take yet", tone: "bg-red text-white" },
  check: { text: "Check prereqs", tone: "border border-ink" },
};

function seats(open: number | null): string {
  if (open === null) return "";
  return open === 0 ? "full" : `${open} open`;
}

/** Searchable course list for the term. All rows come from the term data (no LLM). */
export function Catalog({ session, open, busy, scheduled, onClose, onAdd }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    const timer = setTimeout(() => {
      searchCatalog(session, query.trim(), abort.signal)
        .then((r) => {
          setResults(r);
          setError(null);
        })
        .catch((e: unknown) => {
          if (!abort.signal.aborted) setError(e instanceof Error ? e.message : String(e));
        });
    }, 200);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [session, query, open]);

  const searching = query.trim() !== "";
  const heading = searching
    ? `${results?.total ?? "…"} match${results?.total === 1 ? "" : "es"}`
    : "Counts toward your degree";

  return (
    <div
      className="flex h-full flex-col"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <header className="flex items-center justify-between border-b-2 border-ink bg-yellow px-5 py-4">
        <h2 className="text-sm font-bold uppercase tracking-[0.25em]">Course catalog</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close catalog"
          className="text-xl font-bold leading-none hover:text-red"
        >
          ←
        </button>
      </header>

      <input
        ref={input}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search code, title or instructor"
        aria-label="Search the catalog"
        className="w-full border-b-2 border-ink bg-white px-5 py-3.5 text-sm placeholder:text-ink/40 focus:outline-none"
      />

      <div className="flex items-center justify-between px-5 pb-2 pt-4">
        <span className="label">{heading}</span>
        {results && results.total > results.courses.length && (
          <span className="text-[11px] text-ink/50">showing {results.courses.length}</span>
        )}
      </div>

      {error && <p className="px-5 text-sm text-red">{error}</p>}

      <ul className="thin-scroll flex-1 overflow-y-auto px-5 pb-6">
        {results?.courses.map((c) => {
          const status = STATUS[c.status];
          const isOpen = expanded === c.code;
          const canAdd = !busy && c.status !== "taken" && c.status !== "blocked" && c.sections.length > 0;
          return (
            <li key={c.code} className="border-t-2 border-ink py-3">
              <div className="flex items-start gap-3">
                <button
                  type="button"
                  onClick={() => setExpanded(isOpen ? null : c.code)}
                  aria-expanded={isOpen}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="text-sm font-bold">{c.code}</span>
                    <span className="text-[11px] text-ink/50">{c.credits} cr</span>
                    <span className="text-[11px] text-ink/40">
                      {c.sections.length} section{c.sections.length === 1 ? "" : "s"} {isOpen ? "▴" : "▾"}
                    </span>
                  </div>
                  <div className="truncate text-sm">{c.title}</div>
                </button>
                {scheduled.has(c.code) ? (
                  <span className="flex shrink-0 items-center gap-1 bg-blue px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-white">
                    <Shape kind="circle" className="h-1.5 w-1.5" /> Planned
                  </span>
                ) : (
                  <button
                    type="button"
                    disabled={!canAdd}
                    onClick={() => onAdd(c)}
                    title={`Ask the assistant to add ${c.code}`}
                    className="shrink-0 border-2 border-ink px-2 py-0.5 text-xs font-bold uppercase tracking-wider hover:bg-ink hover:text-paper disabled:border-ink/20 disabled:text-ink/30 disabled:hover:bg-transparent"
                  >
                    + Add
                  </button>
                )}
              </div>

              {(status || c.counts_toward.length > 0) && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {status && (
                    <span
                      className={`px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${status.tone}`}
                    >
                      {status.text}
                    </span>
                  )}
                  {c.counts_toward.map((t) => (
                    <span
                      key={t}
                      className="bg-yellow px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
              {c.notes.length > 0 && <p className="mt-1 text-[11px] text-ink/60">{c.notes.join("; ")}</p>}

              {isOpen && (
                <table className="mt-3 w-full text-[11px]">
                  <tbody>
                    {c.sections.length === 0 && (
                      <tr>
                        <td className="py-1 text-ink/50">No sections this term.</td>
                      </tr>
                    )}
                    {c.sections.map((s) => (
                      <tr key={s.id} className="border-t border-rule align-top">
                        <td className="whitespace-nowrap py-1 pr-2 font-semibold">
                          {s.id.slice(c.code.length).trim() || s.id}
                          {s.component !== "LEC" && (
                            <span className="ml-1 font-normal text-ink/50">{s.component}</span>
                          )}
                        </td>
                        <td className="py-1 pr-2">{s.online ? "Online" : s.when}</td>
                        <td className="py-1 pr-2 text-ink/70">{s.instructors.join(", ") || "TBA"}</td>
                        <td className="whitespace-nowrap py-1 text-right tabular-nums text-ink/60">
                          {seats(s.seats_open)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </li>
          );
        })}
        {results && results.courses.length === 0 && (
          <li className="border-t-2 border-ink py-6 text-sm text-ink/60">
            {searching ? "Nothing matches that this term." : "Nothing left to count toward. Try a search."}
          </li>
        )}
      </ul>
    </div>
  );
}
