"use client";

import { useEffect, useRef, useState } from "react";
import type { View } from "@/lib/api";
import { Doodle } from "./palette";

export interface Line {
  who: "you" | "planner";
  text: string;
}

interface Props {
  lines: Line[];
  questions: View["questions"];
  choices: View["choices"];
  suggestions: View["suggestions"];
  busy: boolean;
  onSend: (text: string, shown?: string) => void;
  onChoose: (number: number, text: string) => void;
}

export function Chat({ lines, questions, choices, suggestions, busy, onSend, onChoose }: Props) {
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
    <div className="ruled flex h-full flex-col">
      <header className="flex items-end gap-2 border-b-2 border-ink/80 bg-paper py-3 pl-14 pr-5">
        <Doodle kind="star" className="mb-1 h-6 w-6 text-pen-red" />
        <h2 className="font-marker text-3xl font-bold leading-none">Planner buddy</h2>
      </header>

      <div className="thin-scroll flex-1 space-y-5 overflow-y-auto py-5 pl-14 pr-5">
        {lines.map((line, i) =>
          line.who === "you" ? (
            <div key={i} className="flex justify-end pt-2">
              <p
                className="tape relative max-w-[88%] whitespace-pre-wrap bg-hl-yellow px-4 pb-3 pt-4 shadow-[2px_3px_0_rgba(39,48,74,0.14)]"
                style={{ transform: `rotate(${i % 2 ? 1.2 : -1}deg)` }}
              >
                {line.text}
              </p>
            </div>
          ) : (
            <div key={i} className="relative">
              <Doodle kind="arrow" className="absolute -left-10 top-0 h-6 w-6 text-pen-blue" />
              <pre className="whitespace-pre-wrap font-sans text-[15px] leading-7 text-pen-blue">{line.text}</pre>
            </div>
          ),
        )}
        {!busy && suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2" aria-label="Suggested follow-ups">
            {suggestions.map((s, i) => (
              <button
                key={s.message}
                type="button"
                onClick={() => onSend(s.message, s.message.startsWith("/") ? s.label : s.message)}
                className={`sketch sketch-thin flex items-center gap-1 bg-paper px-2.5 py-0.5 text-sm text-pen-blue hover:bg-hl-blue ${
                  i % 2 ? "sketch-alt" : ""
                }`}
              >
                <Doodle kind={s.message === "/undo" ? "spiral" : "arrow"} className="h-3.5 w-3.5" strokeWidth={2.2} />
                {s.label}
              </button>
            ))}
          </div>
        )}
        {busy && (
          <div className="flex items-center gap-2 text-pencil" aria-label="Working on it">
            <Doodle kind="spiral" className="h-5 w-5 animate-spin" />
            <span className="font-marker text-xl">thinking…</span>
          </div>
        )}
        <div ref={end} />
      </div>

      {choices.length > 0 && (
        <div className="border-t-2 border-dashed border-ink/40 bg-hl-yellow/40 py-3 pl-14 pr-5">
          <p className="font-marker text-xl font-bold leading-none">Pick one:</p>
          <div className="mt-2 space-y-2">
            {choices.map((c) => (
              <button
                key={c.number}
                type="button"
                disabled={busy}
                onClick={() => onChoose(c.number, c.text)}
                className={`sketch sketch-thin flex w-full items-start gap-2 bg-paper px-3 py-1.5 text-left hover:bg-hl-green disabled:opacity-40 ${
                  c.number % 2 ? "" : "sketch-alt"
                }`}
              >
                <span className="font-marker text-lg font-bold leading-6 text-pen-red">{c.number}.</span>
                <span className="leading-6">{c.text}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {questions.length > 0 && (
        <div className="space-y-3 border-t-2 border-dashed border-ink/40 bg-paper/80 py-3 pl-14 pr-5">
          {questions.map((q) => (
            <div key={q.question}>
              <p>{q.question}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {q.options.map((o, i) => (
                  <button
                    key={o}
                    type="button"
                    disabled={busy}
                    onClick={() => onSend(o)}
                    className={`sketch sketch-thin bg-paper px-3 py-0.5 hover:bg-hl-green disabled:opacity-40 ${
                      i % 2 ? "sketch-alt" : ""
                    }`}
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
        className="flex items-end gap-3 border-t-2 border-ink/80 bg-paper py-3 pl-14 pr-4"
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
          placeholder="write here… e.g. no classes before 10, Fridays off"
          className="ruled flex-1 resize-none bg-transparent px-1 text-[15px] leading-7 placeholder:text-pencil/70 focus:outline-none"
          style={{ backgroundImage: "linear-gradient(transparent calc(1.75rem - 1px), #CFDDEB calc(1.75rem - 1px))" }}
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          aria-label="Send"
          className="sketch mb-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-hl-pink transition-transform hover:rotate-12 disabled:bg-paper disabled:opacity-50"
        >
          <Doodle kind="arrow" className="h-6 w-6" strokeWidth={2.2} />
        </button>
      </form>
    </div>
  );
}
