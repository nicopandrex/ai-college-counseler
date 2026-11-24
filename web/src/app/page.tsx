"use client";

import { useState } from "react";
import { Canvas } from "@/components/Canvas";
import { Catalog } from "@/components/Catalog";
import { Chat, type Line } from "@/components/Chat";
import { Mark, Shape } from "@/components/palette";
import { dropRule, sendMessage, startSession, type Turn, type View } from "@/lib/api";
import { termName } from "@/lib/format";

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
      setView(turn.view);
      setPicked(0);
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

  const send = (text: string) => void run(() => sendMessage(session, text), text);
  const index = Math.min(picked, Math.max(view.schedules.length - 1, 0));
  const scheduled = new Set(view.schedules[index]?.sections.map((s) => s.course) ?? []);
  const facts = view.facts;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-16 shrink-0 items-stretch border-b-2 border-ink">
        <div className="flex items-center gap-3 px-6">
          <Mark size="h-3.5 w-3.5" />
          <span className="text-sm font-bold uppercase tracking-[0.3em]">Degree Planner</span>
        </div>
        <div className="flex flex-col justify-center border-l-2 border-ink px-6">
          <span className="label text-ink/50">Planning</span>
          <span className="text-base font-bold leading-tight">{termName(view.term)}</span>
        </div>
        {facts.credits_earned !== null && (
          <div className="hidden flex-col justify-center border-l-2 border-ink px-6 md:flex">
            <span className="label text-ink/50">Credits</span>
            <span className="text-base font-bold leading-tight tabular-nums">
              {facts.credits_earned}
              {facts.credits_in_progress ? (
                <span className="font-normal text-ink/60"> + {facts.credits_in_progress} in progress</span>
              ) : null}
            </span>
          </div>
        )}
        {facts.standing && (
          <div className="hidden flex-col justify-center border-l-2 border-ink px-6 lg:flex">
            <span className="label text-ink/50">Standing</span>
            <span className="text-base font-bold capitalize leading-tight">{facts.standing}</span>
          </div>
        )}
        {error && (
          <div className="ml-auto flex items-center gap-2 bg-red px-6 text-sm text-white" role="alert">
            <Shape kind="triangle" className="h-3 w-3" /> {error}
          </div>
        )}
      </header>

      <div className="flex min-h-0 flex-1">
        <button
          type="button"
          onClick={() => setCatalogOpen((o) => !o)}
          aria-expanded={catalogOpen}
          aria-controls="catalog"
          className={`flex w-12 shrink-0 flex-col items-center gap-4 border-r-2 border-ink pt-5 transition-colors ${
            catalogOpen ? "bg-ink text-yellow" : "bg-yellow text-ink hover:bg-ink hover:text-yellow"
          }`}
        >
          <span className="text-lg font-bold leading-none">{catalogOpen ? "←" : "→"}</span>
          <span className="label [writing-mode:vertical-rl] rotate-180">Course catalog</span>
        </button>

        <div className="relative min-w-0 flex-1 overflow-hidden">
          <aside
            id="catalog"
            aria-hidden={!catalogOpen}
            className={`absolute inset-y-0 left-0 z-20 w-[420px] max-w-full border-r-2 border-ink bg-paper transition-[transform,visibility] duration-300 ease-out ${
              catalogOpen ? "visible translate-x-0 shadow-[10px_0_0_0_rgba(20,20,20,0.12)]" : "invisible -translate-x-full"
            }`}
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
            <div
              className="absolute inset-0 z-10 bg-paper/40"
              onClick={() => setCatalogOpen(false)}
              aria-hidden
            />
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

        <aside className="w-[400px] shrink-0 border-l-2 border-ink bg-paper">
          <Chat lines={lines} questions={busy ? [] : view.questions} busy={busy} onSend={send} />
        </aside>
      </div>
    </div>
  );
}

function Upload({ busy, error, onFile }: { busy: boolean; error: string | null; onFile: (f: File) => void }) {
  const [over, setOver] = useState(false);
  return (
    <main className="grid min-h-screen lg:grid-cols-[1fr_1.1fr]">
      <section aria-hidden className="relative hidden overflow-hidden border-r-2 border-ink lg:block">
        <div className="absolute left-[8%] top-[8%] aspect-square w-[56%] rounded-full bg-red" />
        <div className="absolute bottom-0 right-0 h-[48%] w-[46%] bg-blue" />
        <div
          className="absolute bottom-[8%] left-[6%] h-[34%] w-[40%] bg-yellow"
          style={{ clipPath: "polygon(50% 0, 100% 100%, 0 100%)" }}
        />
        <div className="absolute left-0 top-[58%] h-3 w-[72%] bg-ink" />
        <div className="absolute right-[16%] top-0 h-[62%] w-3 bg-ink" />
        <div className="absolute right-[8%] top-[12%] h-16 w-16 rounded-full border-[6px] border-ink" />
        <p className="absolute bottom-6 left-6 text-[10px] font-semibold uppercase tracking-[0.4em]">
          Mo · Tu · We · Th · Fr
        </p>
      </section>

      <section className="flex flex-col justify-center px-8 py-12 sm:px-14 lg:px-20">
        <div className="flex items-center gap-3">
          <Mark size="h-3.5 w-3.5" />
          <span className="label">Degree Planner · UVM</span>
        </div>
        <h1 className="mt-8 text-5xl font-bold uppercase leading-[0.95] tracking-tight sm:text-6xl">
          Your next
          <br />
          semester,
          <br />
          <span className="text-red">solved.</span>
        </h1>

        <ol className="mt-10 grid max-w-xl gap-4 border-t-2 border-ink pt-6 sm:grid-cols-3">
          {[
            ["01", "Upload your DegreeWorks audit"],
            ["02", "Say what you want in plain words"],
            ["03", "Pick from schedules that count"],
          ].map(([n, text]) => (
            <li key={n}>
              <span className="text-2xl font-bold tabular-nums">{n}</span>
              <p className="mt-1 text-sm text-ink/70">{text}</p>
            </li>
          ))}
        </ol>

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
          className={`mt-10 flex max-w-xl cursor-pointer items-center justify-between border-2 border-ink px-6 py-5 transition-colors ${
            over ? "bg-yellow" : "bg-white hover:bg-yellow"
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
          <span>
            <span className="block text-base font-bold uppercase tracking-wider">
              {busy ? "Reading your audit…" : "Choose your audit PDF"}
            </span>
            <span className="text-xs text-ink/60">
              {busy ? "Up to a minute the first time." : "Or drop it here."}
            </span>
          </span>
          {busy ? (
            <span className="flex gap-1.5">
              {["bg-red", "bg-blue", "bg-yellow"].map((c, i) => (
                <span
                  key={c}
                  className={`h-3 w-3 animate-pulsebar ${c}`}
                  style={{ animationDelay: `${i * 150}ms` }}
                />
              ))}
            </span>
          ) : (
            <span className="text-3xl font-bold leading-none">↑</span>
          )}
        </label>
        {error && (
          <p className="mt-3 flex max-w-xl items-center gap-2 bg-red px-4 py-2 text-sm text-white" role="alert">
            <Shape kind="triangle" className="h-3 w-3" /> {error}
          </p>
        )}
        <p className="mt-6 max-w-xl text-xs text-ink/50">
          Your audit is read on this computer&apos;s planner server and not saved. Always check your
          plan with your advisor.
        </p>
      </section>
    </main>
  );
}
