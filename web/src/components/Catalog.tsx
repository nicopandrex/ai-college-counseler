"use client";

import { useEffect, useRef, useState } from "react";
import { searchCatalog, type Catalog as Results, type CatalogCourse } from "@/lib/api";
import { splitTitle } from "@/lib/progress";
import { Doodle } from "./palette";

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
  taken: { text: "already taken", tone: "text-pencil line-through" },
  blocked: { text: "can't take yet", tone: "text-pen-red" },
  check: { text: "check prereqs", tone: "text-pen-blue" },
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
    : "These count toward your degree";

  return (
    <div
      className="flex h-full flex-col"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <header className="flex items-center justify-between px-5 pb-2 pt-4">
        <h2 className="font-marker text-3xl font-bold leading-none">
          <span className="scribble-underline">Course catalog</span>
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close catalog"
          className="font-marker text-3xl leading-none text-pencil hover:text-pen-red"
        >
          ✕
        </button>
      </header>

      <div className="px-5 pb-1 pt-2">
        <label className="sketch flex items-center gap-2 bg-paper px-3 py-1.5">
          <Doodle kind="circle" className="h-5 w-5 text-pencil" />
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search a code, title or teacher…"
            aria-label="Search the catalog"
            className="w-full bg-transparent text-[15px] placeholder:text-pencil/70 focus:outline-none"
          />
        </label>
      </div>

      <div className="flex items-baseline justify-between px-5 pb-1 pt-3">
        <span className="font-marker text-xl font-bold text-pencil">{heading}</span>
        {results && results.total > results.courses.length && (
          <span className="text-xs text-pencil">showing {results.courses.length}</span>
        )}
      </div>

      {error && <p className="px-5 text-pen-red">{error}</p>}

      <ul className="thin-scroll flex-1 space-y-4 overflow-y-auto px-5 pb-6 pt-2">
        {results?.courses.map((c, i) => {
          const status = STATUS[c.status];
          const isOpen = expanded === c.code;
          const canAdd = !busy && c.status !== "taken" && c.status !== "blocked" && c.sections.length > 0;
          return (
            <li
              key={c.code}
              className={`sketch sketch-thin bg-paper px-4 py-3 shadow-[2px_3px_0_rgba(39,48,74,0.08)] ${
                i % 2 ? "sketch-alt" : ""
              }`}
            >
              <div className="flex items-start gap-3">
                <button
                  type="button"
                  onClick={() => setExpanded(isOpen ? null : c.code)}
                  aria-expanded={isOpen}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="font-marker text-xl font-bold leading-none">{c.code}</span>
                    <span className="text-xs text-pencil">
                      {c.credits} cr · {c.sections.length} section{c.sections.length === 1 ? "" : "s"}{" "}
                      {isOpen ? "▴" : "▾"}
                    </span>
                  </div>
                  <div className="truncate">{c.title}</div>
                </button>
                {scheduled.has(c.code) ? (
                  <span className="flex shrink-0 items-center gap-1 font-marker text-lg font-bold text-pen-blue">
                    <Doodle kind="check" className="h-5 w-5" strokeWidth={2.6} /> planned
                  </span>
                ) : (
                  <button
                    type="button"
                    disabled={!canAdd}
                    onClick={() => onAdd(c)}
                    title={`Ask the assistant to add ${c.code}`}
                    className="sketch sketch-thin shrink-0 bg-hl-green px-2.5 font-marker text-lg font-bold hover:-rotate-3 disabled:bg-transparent disabled:text-pencil/50 disabled:hover:rotate-0"
                  >
                    + add
                  </button>
                )}
              </div>

              {status && <div className={`mt-1 text-sm ${status.tone}`}>{status.text}</div>}
              {c.counts_toward.length > 0 && (
                <ul className="mt-1 text-sm">
                  {c.counts_toward.map((t) => (
                    <li key={t} className="flex items-start gap-1.5 text-pen-blue" title={t}>
                      <Doodle kind="arrow" className="mt-0.5 h-3.5 w-3.5" strokeWidth={2.2} />
                      {splitTitle(t).name}
                    </li>
                  ))}
                </ul>
              )}
              {c.notes.length > 0 && <p className="mt-1 text-sm text-pencil">{c.notes.join("; ")}</p>}

              {isOpen && (
                <table className="mt-2 w-full text-sm">
                  <tbody>
                    {c.sections.length === 0 && (
                      <tr>
                        <td className="py-1 text-pencil">No sections this term.</td>
                      </tr>
                    )}
                    {c.sections.map((s) => (
                      <tr key={s.id} className="border-t border-dashed border-ruled align-top">
                        <td className="whitespace-nowrap py-1 pr-2 font-marker text-base font-bold">
                          {s.id.slice(c.code.length).trim() || s.id}
                          {s.component !== "LEC" && (
                            <span className="ml-1 font-sans text-xs font-normal text-pencil">{s.component}</span>
                          )}
                        </td>
                        <td className="py-1 pr-2">{s.online ? "Online" : s.when}</td>
                        <td className="py-1 pr-2 text-pencil">{s.instructors.join(", ") || "TBA"}</td>
                        <td className="whitespace-nowrap py-1 text-right text-pencil">{seats(s.seats_open)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </li>
          );
        })}
        {results && results.courses.length === 0 && (
          <li className="py-6 text-center font-marker text-2xl text-pencil">
            {searching ? "nothing matches that this term :(" : "nothing left to count toward. try a search!"}
          </li>
        )}
      </ul>
    </div>
  );
}
