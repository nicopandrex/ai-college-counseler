"use client";

import { useEffect, useRef, useState } from "react";
import type { View } from "@/lib/api";
import { Shape } from "./palette";

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
      <header className="flex items-center gap-3 border-b-2 border-ink px-5 py-4">
        <Shape kind="circle" className="h-4 w-4 text-red" />
        <h2 className="text-sm font-bold uppercase tracking-[0.25em]">Assistant</h2>
      </header>

      <div className="thin-scroll flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {lines.map((line, i) =>
          line.who === "you" ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap bg-blue px-3.5 py-2.5 text-sm text-white">
                {line.text}
              </p>
            </div>
          ) : (
            <div key={i} className="flex gap-3">
              <Shape kind="square" className="mt-1.5 h-2 w-2 shrink-0 text-red" />
              <pre className="min-w-0 flex-1 whitespace-pre-wrap font-sans text-sm leading-relaxed">
                {line.text}
              </pre>
            </div>
          ),
        )}
        {busy && (
          <div className="flex items-center gap-1.5 pl-5" aria-label="Working on it">
            {["bg-red", "bg-blue", "bg-yellow"].map((c, i) => (
              <span
                key={c}
                className={`h-2 w-2 animate-pulsebar ${c}`}
                style={{ animationDelay: `${i * 150}ms` }}
              />
            ))}
          </div>
        )}
        <div ref={end} />
      </div>

      {questions.length > 0 && (
        <div className="space-y-3 border-t-2 border-ink px-5 py-3">
          {questions.map((q) => (
            <div key={q.question} className="text-sm">
              <p className="font-medium">{q.question}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {q.options.map((o) => (
                  <button
                    key={o}
                    type="button"
                    disabled={busy}
                    onClick={() => onSend(o)}
                    className="border-2 border-ink px-2.5 py-1 text-xs font-medium hover:bg-yellow disabled:opacity-40"
                  >
                    {o}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <form
        className="flex border-t-2 border-ink"
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
          rows={3}
          aria-label="Message the assistant"
          placeholder="No classes before 10, Fridays off, macro but not with Rodrigues…"
          className="flex-1 resize-none bg-white px-5 py-4 text-sm placeholder:text-ink/40 focus:outline-none"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          aria-label="Send"
          className="w-16 shrink-0 border-l-2 border-ink bg-ink text-2xl text-paper transition-colors hover:bg-red disabled:bg-ink/30"
        >
          →
        </button>
      </form>
    </div>
  );
}
