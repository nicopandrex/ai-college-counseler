"use client";

import { useState } from "react";
import { Canvas } from "@/components/Canvas";
import { Chat, type Line } from "@/components/Chat";
import { dropRule, sendMessage, startSession, type Turn, type View } from "@/lib/api";

export default function Home() {
  const [session, setSession] = useState<string | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(work: () => Promise<Turn & { id?: string }>, said?: string) {
    setBusy(true);
    setError(null);
    if (said) setLines((l) => [...l, { who: "you", text: said }]);
    try {
      const turn = await work();
      if (turn.id) setSession(turn.id);
      setView(turn.view);
      setLines((l) => [...l, { who: "planner", text: turn.reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!session || !view) {
    return (
      <main className="mx-auto max-w-xl p-8">
        <h1 className="text-2xl font-semibold">Degree Planner</h1>
        <p className="mt-2 text-sm text-slate-600">
          Upload your DegreeWorks audit (PDF). Then tell me what you want next semester and
          I&apos;ll build schedules that count toward your degree.
        </p>
        <label className="mt-6 block rounded border-2 border-dashed border-slate-300 p-6 text-center text-sm hover:bg-slate-50">
          <input
            type="file"
            accept="application/pdf"
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void run(() => startSession(file));
            }}
          />
          {busy ? "Reading your audit… (up to a minute the first time)" : "Choose your audit PDF"}
        </label>
        {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
        <p className="mt-4 text-xs text-slate-500">
          Your audit is read on this computer&apos;s planner server and not saved. Always check
          your plan with your advisor.
        </p>
      </main>
    );
  }

  const send = (text: string) => void run(() => sendMessage(session, text), text);
  return (
    <main className="grid h-screen grid-cols-1 gap-4 p-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <div className="flex min-h-0 flex-col">
        <h1 className="mb-2 text-lg font-semibold">Degree Planner · {view.term}</h1>
        <div className="min-h-0 flex-1">
          <Chat lines={lines} questions={busy ? [] : view.questions} busy={busy} onSend={send} />
        </div>
        {error && <p className="mt-2 text-sm text-red-700">{error}</p>}
      </div>
      <div className="min-h-0 overflow-y-auto rounded border border-slate-200 p-4">
        <Canvas
          view={view}
          busy={busy}
          onSend={send}
          onDrop={(rule) => void run(() => dropRule(session, rule))}
        />
      </div>
    </main>
  );
}
