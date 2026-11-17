# PROGRESS

Running log. Resume from **Current status**. Newest log entries at the top.

## Current status
- **Milestone:** M1, waiting on the owner's golden confirmation and a stable Gemini tier.
- **Next task once unblocked:** M1.7b: record the real extraction (`LLM_CACHE_MODE=record`,
  cache dir `fixtures/private/llm-cache`), fix the prompt/validator until
  `test_private_golden.py` passes against the reviewed golden, then M2.

## Blockers (need owner)
1. **Confirm the golden** (`fixtures/private/golden/audit.golden.json`): the 32 courses and the
   statuses, then `"reviewed": true`. count_unit needs no owner input: the 57 blanks are
   rows where the audit states no unit (correct as null).
2. **Gemini free tier is unreliable and keeps prompts for training.** 3.5-flash returns 503s
   for long stretches; Pro models have zero free quota. Enabling billing on the key fixes both.
   Required before any other student's audit is processed (privacy policy: no training use).

## Milestones

### M0 Scaffold ✅
- [x] CLAUDE.md, PROGRESS.md, .gitignore (fixtures/private/), uv workspace, FastAPI skeleton,
      Next.js 14 + Tailwind + zod + vitest, docker-compose Postgres, Makefile, CI.

### M1 Audit extraction (STOP after draft golden) ⏸
- [x] M1.1 pdfplumber layout pass: table rows → icon-anchored requirement rows, label/content
      split at char level, per-block course columns, paragraph-to-icon assignment
- [x] M1.2 per-school config (`schools/uvm.json`: COLOR_MAP, fonts, column defaults, grades)
- [x] M1.3 vision-fallback hook (stub) for text-less pages and unknown icon colors
- [x] M1.4 `planner_llm`: the one LLM gateway, record/replay cache, Anthropic provider
- [x] M1.5 structuring: verbatim prompt from docs + input-format addendum, strict JSON schema
- [x] M1.6 deterministic validation: quote provenance, icon vs status, count_unit vs wording,
      satisfied_by vs course rows, code format, wildcard flag, row coverage, credit/class
      sums, catalog year; flagged items capped at 0.5 confidence → `needs_review`
- [x] M1.7a draft golden generated deterministically → `fixtures/private/golden/` (**STOP**)
- [~] M1.7b record the real LLM extraction. First Gemini run: 109 requirements, 16 issues, all
      real; fixed above. Re-recording blocked by free-tier 503s.
- [ ] M1.8 `test_private_golden.py` green against the reviewed golden

### M2 derive_state … M10 Beta-ready
Not started. Done-bars in CLAUDE.md and the build plan.

## Facts that differ from the plan
- **Blue icon = in progress, not "informational".** The audit legend: blue
  `(0.1569, 0.4549, 0.7333)` = "Complete except for in-progress classes". Every blue row in the
  real audit is satisfied by an IP course (CS 3240, EDFS 1010, …). The diversity note the plan
  calls "info" is blue because EDFS 1010 is in progress. Treating blue as info would drop real
  requirements.
- **Two more legend colors:** olive `(0.5412, 0.4157, 0)` = "Nearly complete" (→ incomplete),
  `(0.0078, 0.4196, 0.7843)` = "Prerequisite needed". Both are in `uvm.json`.
- **The incomplete icon has a white fill under the red ring.** Classifying curve by curve
  ("other colors = info") would misread it. Curves are grouped into icons; white/black are
  neutral.
- **`extract_tables()` does not separate columns on UVM audits.** Each table row is a single
  cell, and label and content lines still interleave inside it ("Total Credit Requirement"
  spliced into the "Still needed" paragraph). Fix: use table rows only as row boxes, split
  *characters* by x at the block's "Course" column, then form words. Word-level splitting
  is not enough: "additional" + "CS" merge into one word across the column boundary.
- **One table row can hold several requirements** (Total Credit / Residency / A&S credits /
  GPA). Each icon anchors a sub-row. Multi-line text is vertically centred on its label, so
  whole paragraphs are assigned to the nearest icon band.
- **Credit sums reconcile exactly**: degree "Credits applied: 95" = sum of unique course rows;
  In-progress 15; Chinese major 28; CS 35. These are now deterministic checks.

## Decisions
- **Owner choices (2026-11-17):** LLM provider = Gemini. Target term = Spring 2027, but the product
  stays term-agnostic. In-progress courses count as passed (`assume_pass`, already the
  `derive_state` default). CS 3050 Software Engineering is in progress, so it counts as taken;
  the demo query's "software engineering" must be caught as already taken, not scheduled.
- **Gemini via its OpenAI-compatible endpoint** (`planner_llm.providers.gemini`): the key goes as a
  Bearer token, the form the environment's secure credential store supports.
  Extraction model `gemini-3.5-flash` (the only free-tier model that answered). Retries
  429/500/503 with backoff.
- **Rule nesting depth 2** in the LLM schema: depth 4 exceeds Gemini's schema-state limit, and
  depth 2 covers the deepest real nesting (any_of → all_of → course_list).
- **Attribute-designation rules** ("1 course with a WIL1 designation") are `course_list` with
  `from: ["@ @ with attribute = WIL1"]`, DegreeWorks' own selector notation. This keeps the
  courses-vs-credits unit structured; the M4 solver resolves it against catalog attributes.
- **Quotes are matched after stripping renderer tags** (BLOCK/ROW/COURSE, `[icon: …]`): the first
  real run quoted "BLOCK Catamount Core", which matched an unrelated row ("…this block Catamount
  Core…") and mis-anchored the block.
- **req_ids are structure-derived slugs**, e.g. `computer_science_major.senior_seminar` or
  `chinese_major.choose_one_track.track_1.1st_year_college_chinese_i`. The LLM is not asked to
  produce stable ids. The plan suggested hashing block title + catalog year; readable slugs
  serve the NL translator better and are equally deterministic. Filler words are dropped
  before truncating to 6 words so similar labels stay distinct.
- **courses_taken is rebuilt from parsed course lines**, not taken from the LLM. Course rows are
  exact in the layout; the LLM's list is only compared (mismatches → issues).
  `applied_to_req_ids` = requirements whose rows list the course.
- **The LLM output is flagged, not overridden** (status, rules, satisfied_by): on a mismatch the
  confidence is capped and the item goes to review, per the plan.
- **Draft golden comes from the deterministic layer**, not the LLM under test. It covers the
  done-bar fields only (requirement status + count_unit, course fields). count_unit is
  drafted from document wording ("N Credits in…", "N Classes in…"), or null where unclear.
- **Summary fields are allow-listed** (Program, Level, Class, College, Degree, Majors, …).
  Student name, NetID and advisors are never extracted or sent to the LLM.
- **Separate `/llm` workspace package (`planner_llm`)** holds the single LLM gateway, so ingest
  and the M6 translator share it.
- **Rule recursion unrolled to depth 4** in the LLM schema (structured outputs reject recursive
  schemas). The Chinese major needs depth 3 (any_of → all_of → course_list).
- **Default extraction model `claude-opus-5-5`, effort `high`, server-side refusal fallbacks
  on.** Accuracy-critical batch work, per the plan.
- Python import names `planner_ingest` / `planner_llm` / `planner_solver`; pytest importlib
  mode otherwise shadows the packages with the top-level dirs.

## Schema proposals
_(none yet)_

## Open questions
- **M6 note (not a contract change):** structured outputs require
  `additionalProperties: false` on every object, but the contract's `params` is a loose
  object. Plan: the LLM-facing schema uses a per-type params union (from the reference doc),
  and output is validated against `constraint-spec.schema.json` before it crosses the
  boundary.
- **Preregistered courses:** this audit shows none (no Spring 2027 registrations yet), so the
  DegreeWorks marker is unknown. `preregistered_grades` is empty in `uvm.json` until one is
  seen.
- **Next.js 14 advisories:** `next@14.2.35` is the last 14.x; fixes exist only in 15+. Decide
  before the M10 deploy.
- **No Docker daemon in this container:** compose is written but unexercised; tests don't need
  Postgres.

## out_of_scope requests discovered
_(none yet)_

## Log
- **2026-11-17 · M1.** Added the Gemini provider; the key is saved via the secure form. A live
  synthetic run passed end to end, and the validator caught a garbled grade ("B configuration"
  vs B+). Real run: 109 requirements; fixed tag-quote mis-anchoring and attribute-code misuse.
  Re-record pending (Gemini 503s).
- **2026-11-16 · M1.** Built the deterministic layout pass, icon classifier, UVM config,
  vision hook, LLM gateway, structuring prompt + strict schema, validator, deterministic
  req_ids, golden draft/compare, CLI, and a synthetic DegreeWorks PDF generator for committed
  tests. 46 tests green. Real audit: 8 blocks, 104 rows, 32 courses, no layout warnings.
  Drafted the golden; stopped for hand-correction and LLM access.
- **2026-11-16 · M0.** Scaffolded the monorepo; `make test` green.
