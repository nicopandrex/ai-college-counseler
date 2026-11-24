"use client";

import { useEffect, useRef, useState } from "react";
import type { View } from "@/lib/api";

export interface Line {
  who: "you" | "planner";
  text: string;
}

interface Props {
  lines: Line[];
  questions: View["questions"];
  busy: boolean;
  onSend: (text: string) => void;
}

export function Chat({ lines, questions, busy, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, busy]);

  function submit() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    onSend(text);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        {lines.map((line, i) => (
          <div key={i} className={line.who === "you" ? "flex justify-end" : ""}>
            <pre
              className={`whitespace-pre-wrap rounded-lg px-3 py-2 font-sans text-sm ${
                line.who === "you" ? "max-w-[85%] bg-slate-800 text-white" : "bg-slate-100"
              }`}
            >
              {line.text}
            </pre>
          </div>
        ))}
        {busy && <p className="text-sm text-slate-500">Working on it…</p>}
        <div ref={end} />
      </div>
      {questions.map((q) => (
        <div key={q.question} className="mt-2 text-sm">
          <p className="text-slate-700">{q.question}</p>
          <div className="mt-1 flex flex-wrap gap-2">
            {q.options.map((o) => (
              <button
                key={o}
                type="button"
                disabled={busy}
                onClick={() => onSend(o)}
                className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40"
              >
                {o}
              </button>
            ))}
          </div>
        </div>
      ))}
      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          placeholder="e.g. no classes before 10, Fridays off, and macro but not with Rodrigues"
          className="flex-1 resize-none rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="rounded bg-slate-800 px-4 text-sm text-white disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}
