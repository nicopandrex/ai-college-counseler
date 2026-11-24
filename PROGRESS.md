# PROGRESS

Running log. Resume from **Current status**. Newest entries at the top of the log.

## Current status
- **Milestone:** M0 done. **Blocked on M1**: the input docs and the audit PDF aren't in the repo (see Blockers).
- **Next task:** M1.1, the pdfplumber table/header/curve-status pass, once the docs and the audit are available.

## Blockers (need owner)
1. `docs/degree-planner-build-plan.md`, `docs/constraint-spec.schema.json`,
   `docs/constraint-spec-reference.md`, `docs/audit-extraction-prompt.md` are missing. The repo
   was empty at session start: no commits, no remote branches. M1, M2 and M4–M6 depend on them.
2. `fixtures/private/` (the real DegreeWorks audit PDF) is missing. Needed for M1 and later.
3. LLM API key + model choice (for `LLM_API_KEY` / `LLM_MODEL`). Needed for the M1 structuring step.

## Milestones

### M0 Scaffold ✅
- [x] CLAUDE.md (condensed rules, architecture, loop protocol)
- [x] .gitignore with `fixtures/private/`, `.env*`, uploads, raw scrape cache, LLM cache
- [x] uv workspace (`ingest`, `solver`), pinned via `uv.lock`; ruff + pytest
- [x] FastAPI solver skeleton (`/health`)
- [x] Next.js 14 + TS + Tailwind + zod + vitest in `/web`, pinned via `package-lock.json`
- [x] docker-compose Postgres 16
- [x] `make install | test | test-py | test-web | lint`; GitHub Actions CI runs install → lint → test
- DONE bar met: `make test` green (smoke tests only).

### M1 Audit extraction (STOP after draft golden)
- [ ] M1.1 pdfplumber pass: `extract_tables()` blocks, header fields, left-margin curve icons (x0 < 60) → status by vertical join
- [ ] M1.2 per-school config (UVM COLOR_MAP)
- [ ] M1.3 vision-fallback hook (stub): zero-text page / single unmatched icon row
- [ ] M1.4 provider-agnostic LLM module with record/replay cache
- [ ] M1.5 LLM structuring via the extraction prompt → pydantic models
- [ ] M1.6 deterministic validation: credit sums, course-code format, status consistency, icon-vs-LLM mismatch → low confidence
- [ ] M1.7 draft golden → `fixtures/private/golden/`, then **STOP** for hand-correction
- [ ] M1.8 golden match test (status, course, grade, credit, count_unit)

### M2 derive_state … M10 Beta-ready
Not started. Done-bars are in CLAUDE.md and the build plan.

## Schema proposals
_(none yet)_

## Open questions
- **Next.js 14 security advisories.** `next@14.2.35` is the last 14.x release; `npm audit` reports
  advisories (RSC DoS, middleware/cache poisoning, SSRF in server actions…) that are fixed only in
  15.x/16.x. That's fine for local dev. Before the M10 deploy, decide: stay on 14 per the stack spec, or move to 15.
- **No Docker daemon in the cloud dev container.** `docker-compose.yml` is written but not
  exercised here. Tests must not require Postgres. DB-backed tests (M3) will use a local
  `postgres` binary if one is available, or be marked to run only where `DATABASE_URL` is set.

## out_of_scope requests discovered
_(none yet)_

## Decisions
- **Python import names are `planner_ingest` / `planner_solver`**, not `ingest` / `solver`. The
  top-level dirs `/ingest` and `/solver` are required by the layout. With pytest's importlib mode,
  test modules get dotted names derived from those dirs (`solver.tests…`), which shadowed the
  installed packages. Distinct names remove the ambiguity.
- **Python 3.13** (container default), `requires-python >=3.12,<3.14`. Pins are exact (`==`) in
  pyproject, and the lockfile is the source of truth.
- **Smoke tests instead of a truly empty suite.** pytest exits 5 on "no tests collected", so each
  package has one real smoke test rather than a hacked exit code.

## Log
- **2026-11-16 · M0.** Scaffolded the monorepo. `make install && make lint && make test` green
  from a clean checkout (Python: 2 passed; web: 2 passed; `next build` ok). Found the repo empty:
  no docs, no fixtures. Blocked on M1.
