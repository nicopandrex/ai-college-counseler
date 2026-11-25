# CLAUDE.md — Degree Planner V0

You are the sole engineer shipping V0 of a degree-planning product. Ship a working,
demoable build; don't brainstorm. Work in a loop until V0 is done.

## Read first, every session
1. `docs/degree-planner-build-plan.md`. Part 1 (V0) is the scope; ignore Part 2 (V1).
2. `docs/constraint-spec.schema.json` + `docs/constraint-spec-reference.md`: **the contract**
   between the LLM layer and the solver. Never change it silently.
3. `docs/audit-extraction-prompt.md`: the extraction prompt and the `derive_state` spec.
4. `PROGRESS.md`: the running log. Always resume from it.

## Product
A student uploads a DegreeWorks audit PDF, then chats in natural language ("next semester:
software engineering, macro but not with Professor Smith, one gen ed, nothing before 10:30").
They get back valid schedules and a multi-term graduation plan, or a precise explanation of
which constraints conflict and how to relax them. School: University of Vermont (UVM).
Test data: `fixtures/private/` (the owner's real audit; never committed).

## Non-negotiable architecture rules
- The LLM never does scheduling math or invents facts. Pipeline:
  language → constraint spec (schema instance) → validation → CP-SAT solver → results → language.
  The LLM touches only the two ends.
- Every fact shown to a user (times, instructors, requirement coverage) is templated from
  solver/database output, never generated. A reply may be reworded by the LLM only through
  `planner_chat.phrasing` (owner decision, 2026-11-24): the rewrite is shown only if it keeps
  the template's facts, otherwise the template is shown.
- Audit ingestion is deterministic-first, **no vision models on the main path**:
  - pdfplumber `extract_tables()` for requirement blocks (`extract_text()` scrambles two-column layouts).
  - Status icons are vector curves in the left margin (x0 < 60): green fill (0.0, 0.502, 0.302) =
    complete; red stroke (0.8314, 0.1569, 0.1569) = incomplete; other colors = info. Join to rows
    by vertical position.
  - COLOR_MAP lives in per-school config, not hardcoded.
  - Vision fallback only for a page with zero extractable text, or a single unmatched icon row.
    Hook built, implementation stubbed.
- The parser keeps `in_progress` distinct. `derive_state` (pure function, no LLM) treats
  in-progress as satisfying by default (`in_progress_policy: assume_pass`), marks
  `provisionally_satisfied`, and tags `pending_grade_risk` on min-grade requirements.
- Every extracted requirement and constraint carries provenance (`source_quote` / `source_text`).
- Constraint ids map to CP-SAT assumption literals so infeasibility returns a minimal conflicting set.
- All LLM calls go through ONE provider-agnostic module (env-configured model + API key) with
  record/replay caching, so tests are deterministic and free to rerun.
- Never commit `fixtures/private/` or any real student data. Committed tests use synthetic or
  anonymized fixtures only.

## Stack / layout
- `/ingest` (Python, `planner_ingest`): audit PDF → structured audit; `derive_state`.
  CLI: `uv run python -m planner_ingest {layout,extract,draft-golden} <pdf>`.
- `/llm` (Python, `planner_llm`): the ONE LLM gateway. Env: `LLM_PROVIDER`, `LLM_MODEL[_<PURPOSE>]`,
  `LLM_API_KEY`, `LLM_CACHE_MODE` (replay|record|live; default replay), `LLM_CACHE_DIR`.
  Real-audit cassettes live in `fixtures/private/llm-cache` (gitignored). Defaults: Flash for
  everything except prerequisite parsing (Pro); `LLM_MAX_LIVE_CALLS` caps every run (default
  30). Sample-run any bulk LLM job and report its token cost before running it in full.
- `data/uvm/` (committed): derived UVM term data + prerequisite answer store. Never re-scrape or
  re-parse what's there; `data/raw/` (gitignored) is only the raw scrape cache.
- `/solver` (Python, `planner_solver`, OR-Tools CP-SAT): validation, term solving (plan mode deferred
  by the owner to a later version).
- `/api` (Python, `planner_api`, FastAPI): the web API over ChatSession. `make dev` runs it with the web.
- `/web` (Next.js 14 + TypeScript + Tailwind): upload, chat, schedule canvas. Plain styling in V0.
- `/docs`, `/evals`, `/fixtures` (`fixtures/private/` is gitignored).
- Postgres via `docker-compose.yml` for dev.
- pydantic (Python) and zod (TS), both validated against the JSON schema.
- Committed tests use the synthetic DegreeWorks PDF generator (`ingest/tests/synth_degreeworks.py`).
- pytest + vitest. Python via a uv workspace (`uv.lock` pins deps); web via npm (`package-lock.json`).
- `make test` runs everything; `make test-py`, `make test-web` run one side each.

## Milestones (in order; details and done-bars in PROGRESS.md)
M0 scaffold · M1 audit extraction (STOP for golden hand-correction) · M2 derive_state ·
M3 UVM data · M4 solver term mode (+ minimal infeasible subset) · M5 validation layer (8 rules) ·
M6 NL translator + 50-utterance eval (≥90%) · M7 CLI demo (STOP, show transcript) ·
M8 plan mode · M9 web UI · M10 beta-ready.

## Loop protocol (every iteration)
1. Read PROGRESS.md; pick the next unchecked task in the current milestone.
2. Write the test first when the task is testable.
3. Implement the smallest thing that passes.
4. Run the FULL suite (`make test`). Never mark anything done with failing tests. Never delete or
   weaken a test to make it pass; fix the code or flag it.
5. Commit with a clear message.
6. Update PROGRESS.md: what was done, what's next, open questions, out_of_scope requests found,
   decisions made and why.
7. Continue. Don't pause to summarize or ask "should I continue?" between tasks.

## Stop and ask the owner ONLY when
- An API key, credentials, or anything needing their login is required.
- Ground truth only they know is needed: hand-correcting golden files, reviewing the eval set,
  sanity-checking plans for their degree.
- A data source is blocked, needs login, or its terms appear to prohibit scraping.
- You want to change the constraint schema contract. Write the proposal in PROGRESS.md under
  "Schema proposals", keep going on other work, and batch these.
- A milestone marked STOP.
When stopping, give a short list of exactly what's needed, then wait.

## Quality bar
- Confidently wrong is the worst failure. Prefer `unparsed` + low confidence + human review over a
  plausible guess, everywhere.
- Small, typed modules. No dead code, no speculative features beyond V0.
- If the plan is factually wrong (e.g. UVM data differs from what was expected), note it in
  PROGRESS.md, adapt, and keep going.
- Git: develop on the assigned `claude/*` branch; push there only.
