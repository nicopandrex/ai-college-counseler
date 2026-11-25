"use client";

import { useState } from "react";
import { Canvas } from "@/components/Canvas";
import { Catalog } from "@/components/Catalog";
import { Chat, type Line } from "@/components/Chat";
import { Doodle } from "@/components/palette";
import { dropRule, sendMessage, startSession, type Turn, type View } from "@/lib/api";
import { termName } from "@/lib/format";

/** Wire coil between two planner pages. */
const COIL =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 28 30'><circle cx='6' cy='15' r='3.2' fill='%23C9BC9F'/><circle cx='22' cy='15' r='3.2' fill='%23C9BC9F'/><path d='M6 15 C 6 6.5, 22 6.5, 22 15' fill='none' stroke='%236E6A75' stroke-width='2.4' stroke-linecap='round'/></svg>\")";

function Spiral() {
  return (
    <div
      aria-hidden
      className="w-7 shrink-0 bg-desk"
      style={{ backgroundImage: COIL, backgroundSize: "28px 30px", backgroundRepeat: "repeat-y" }}
    />
  );
}

export default function Home() {
  const [session, setSession] = useState<string | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState(0);
  const [catalogOpen, setCatalogOpen] = useState(false);

  async function run(work: () => Promise<Turn & { id?: string }>, said?: string) {
    setBusy(true);
    setError(null);
    if (said) setLines((l) => [...l, { who: "you", text: said }]);
    try {
      const turn = await work();
      if (turn.id) setSession(turn.id);
      // stay on the plan being edited; back to the first one only when the plans changed
      if (JSON.stringify(turn.view.schedules) !== JSON.stringify(view?.schedules)) setPicked(0);
      setView(turn.view);
      setLines((l) => [...l, { who: "planner", text: turn.reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!session || !view) {
    return <Upload busy={busy} error={error} onFile={(file) => void run(() => startSession(file))} />;
  }

  const index = Math.min(picked, Math.max(view.schedules.length - 1, 0));
  // the plan on screen goes along, so "add X" edits that plan instead of starting over
  const send = (text: string, shown = text) => void run(() => sendMessage(session, text, index), shown);
  const scheduled = new Set(view.schedules[index]?.sections.map((s) => s.course) ?? []);
  const facts = view.facts;

  return (
    <div className="flex h-screen flex-col bg-desk">
      <header className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-2 px-6 pb-2 pt-3">
        <div className="flex items-center gap-2">
          <Doodle kind="star" className="h-7 w-7 text-pen-red" strokeWidth={2} />
          <h1 className="font-marker text-4xl font-bold leading-none">
            My <span className="scribble-underline">{termName(view.term)}</span> Planner
          </h1>
        </div>
        {facts.credits_earned !== null && (
          <span
            className="sketch sketch-thin bg-hl-green px-3 py-0.5"
            style={{ transform: "rotate(-1.5deg)" }}
          >
            <span className="font-marker text-xl font-bold">{facts.credits_earned} credits</span>
            {facts.credits_in_progress ? (
              <span className="text-pencil"> + {facts.credits_in_progress} in progress</span>
            ) : null}
          </span>
        )}
        {facts.standing && (
          <span
            className="flex h-14 w-14 items-center justify-center rounded-full border-2 border-dashed border-ink bg-hl-blue font-marker text-lg font-bold capitalize leading-none"
            style={{ transform: "rotate(8deg)" }}
          >
            {facts.standing}
          </span>
        )}
        {error && (
          <p
            role="alert"
            className="tape relative ml-auto max-w-md bg-hl-pink px-4 pb-2 pt-3 text-pen-red shadow-[2px_3px_0_rgba(39,48,74,0.14)]"
            style={{ transform: "rotate(1deg)" }}
          >
            {error}
          </p>
        )}
      </header>

      <div className="flex min-h-0 flex-1 pb-3 pr-3">
        <button
          type="button"
          onClick={() => setCatalogOpen((o) => !o)}
          aria-expanded={catalogOpen}
          aria-controls="catalog"
          className={`mt-8 flex h-44 w-10 shrink-0 flex-col items-center justify-center gap-2 rounded-r-2xl border-2 border-l-0 border-ink transition-colors ${
            catalogOpen ? "bg-hl-yellow" : "bg-hl-blue hover:bg-hl-yellow"
          }`}
        >
          <Doodle kind={catalogOpen ? "check" : "flower"} className="h-5 w-5" />
          <span className="rotate-180 font-marker text-xl font-bold [writing-mode:vertical-rl]">Catalog</span>
        </button>

        <div className="sketch relative ml-1 min-w-0 flex-1 overflow-hidden bg-paper shadow-[4px_5px_0_rgba(39,48,74,0.15)]">
          <aside
            id="catalog"
            aria-hidden={!catalogOpen}
            className={`ruled absolute inset-y-0 left-0 z-20 w-[430px] max-w-full border-r-2 border-ink transition-[transform,visibility] duration-300 ease-out ${
              catalogOpen ? "visible translate-x-0 shadow-[8px_0_0_rgba(39,48,74,0.10)]" : "invisible -translate-x-full"
            }`}
            style={{ backgroundImage: "linear-gradient(transparent calc(1.75rem - 1px), #CFDDEB calc(1.75rem - 1px))" }}
          >
            <Catalog
              session={session}
              open={catalogOpen}
              busy={busy}
              scheduled={scheduled}
              onClose={() => setCatalogOpen(false)}
              onAdd={(c) => send(`Add ${c.code} to my schedule`)}
            />
          </aside>
          {catalogOpen && (
            <div className="absolute inset-0 z-10 bg-desk/40" onClick={() => setCatalogOpen(false)} aria-hidden />
          )}
          <main className="thin-scroll h-full overflow-y-auto">
            <Canvas
              view={view}
              index={index}
              busy={busy}
              onPick={setPicked}
              onSend={send}
              onDrop={(rule) => void run(() => dropRule(session, rule))}
            />
          </main>
        </div>

        <Spiral />

        <aside className="sketch sketch-alt w-[400px] shrink-0 overflow-hidden bg-paper shadow-[4px_5px_0_rgba(39,48,74,0.15)]">
          <Chat
            lines={lines}
            questions={busy ? [] : view.questions}
            choices={busy ? [] : view.choices}
            busy={busy}
            onSend={send}
            onChoose={(n, text) => send(String(n), text)}
          />
        </aside>
      </div>
    </div>
  );
}

function Upload({ busy, error, onFile }: { busy: boolean; error: string | null; onFile: (f: File) => void }) {
  const [over, setOver] = useState(false);
  return (
    <main className="flex min-h-screen items-center justify-center bg-desk px-4 py-10">
      <div className="relative w-full max-w-2xl">
        {/* sticky note stuck to the page */}
        <div
          className="tape absolute -right-6 -top-6 z-10 hidden w-48 bg-hl-pink px-4 pb-4 pt-5 shadow-[3px_4px_0_rgba(39,48,74,0.15)] sm:block"
          style={{ transform: "rotate(5deg)" }}
        >
          <p className="font-marker text-2xl font-bold leading-tight">don&apos;t forget!</p>
          <p className="text-sm leading-snug">Always check your plan with your advisor ♡</p>
        </div>

        <div className="sketch ruled px-8 pb-10 pl-16 pt-8 shadow-[5px_6px_0_rgba(39,48,74,0.15)] sm:px-12 sm:pl-20">
          <p className="text-pencil">UVM · Degree Planner</p>
          <h1 className="mt-1 font-marker text-6xl font-bold leading-[0.95] sm:text-7xl">
            Plan my
            <br />
            <span className="scribble-underline">semester!</span>
            <Doodle kind="star" className="ml-3 inline h-10 w-10 -translate-y-6 text-pen-red" strokeWidth={2} />
          </h1>

          <ul className="mt-8 space-y-1 text-lg">
            {[
              "Upload my DegreeWorks audit",
              "Say what I want, in my own words",
              "Pick a schedule that counts toward my degree",
            ].map((text) => (
              <li key={text} className="flex h-7 items-center gap-3">
                <span className="sketch sketch-thin h-5 w-5 shrink-0 bg-paper" aria-hidden />
                {text}
              </li>
            ))}
          </ul>

          <div className="relative mt-10">
            <Doodle
              kind="arrow"
              className="absolute -left-12 -top-8 hidden h-10 w-10 rotate-[30deg] text-pen-blue sm:block"
              strokeWidth={2}
            />
            <label
              onDragOver={(e) => {
                e.preventDefault();
                setOver(true);
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setOver(false);
                const file = e.dataTransfer.files[0];
                if (file && !busy) onFile(file);
              }}
              className={`sketch sketch-dashed tape relative flex cursor-pointer flex-col items-center px-6 py-7 text-center transition-colors ${
                over ? "bg-hl-yellow" : "bg-paper hover:bg-hl-yellow"
              } ${busy ? "pointer-events-none" : ""}`}
            >
              <input
                type="file"
                accept="application/pdf"
                className="sr-only"
                disabled={busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onFile(file);
                }}
              />
              {busy ? (
                <Doodle kind="spiral" className="h-9 w-9 animate-spin text-pen-blue" />
              ) : (
                <Doodle kind="heart" className="h-9 w-9 text-pen-red" />
              )}
              <span className="mt-1 font-marker text-3xl font-bold leading-none">
                {busy ? "reading your audit…" : "drop your audit PDF here"}
              </span>
              <span className="mt-1 text-pencil">
                {busy ? "up to a minute the first time" : "or click to choose it"}
              </span>
            </label>
          </div>
          {error && <p className="mt-3 text-pen-red" role="alert">! {error}</p>}
          <p className="mt-6 text-sm text-pencil">
            Your audit is read on this computer&apos;s planner server and not saved.
          </p>
        </div>
      </div>
    </main>
  );
}
