# PROGRESS

Running log. Resume from **Current status**. Newest log entries at the top.

## Current status
- **Done:** M0, M1, M2, M4 (incl. real solve), M5. M3 is done for Spring 2027 (see gaps).
- **Next:** owner tests the web app (`make dev`, see README); owner reviews the M6 eval set.
  M8 plan mode is deferred to a later version (owner, 2026-11-24).
- **Demo today:** `planner solve --audit fixtures/private/audit.pdf --spec
  fixtures/private/specs/example_senior_seminar.json` (env: `LLM_PROVIDER=gemini
  LLM_MODEL=gemini-3.1-pro-preview LLM_API_KEY=replay-only
  LLM_CACHE_DIR=fixtures/private/llm-cache`). Solves Spring 2027 in ~2 s.

## Blockers / owner input pending
0. **Gemini prepaid credits are depleted** (402). Top up before any new LLM call (new
   extractions, eval re-records, live chat in M7).
0b. **Review the translator eval set**: `evals/translator/REVIEW.md` (M6 STOP).
1. **Owner's standing for Spring 2027**: the audit says junior, so CS 3920 is blocked unless
   `--standing senior` is given.
2. **Past terms for M8**: not available (the owner declined Fall 2026). M8 will treat offering
   patterns as unknown/low confidence.
3. **Prerequisite review queue:** `data/raw/uvm/202701/prereq_review.json` (431 entries; 357
   are usable trees with an unparsed part, 74 are held out and treated as unknown).

## Milestones

### M0 Scaffold ✅
### M1 Audit extraction ✅
- Real audit: 107/107 requirements, 0 validation errors, `test_private_golden.py` green
  against the owner-reviewed golden. Extraction model `gemini-3.1-pro-preview`.
### M2 derive_state ✅
- assume_pass / assume_fail / per_course; earned vs earned_plus_in_progress; preregistered
  unplannable; pending_grade_risk; choice groups keep only the alternative being
  followed. Real audit: Chinese major Track 3 active (only CHIN 4200 left in it); tracks
  1/2/4 not_applicable. "Fail CS 3240" reopens 2 requirements.
### M3 UVM data ✅ Spring 2027 (owner-approved one-time pull)
- soc.uvm.edu FOSE API: 1 search + 1,844 details calls, about 5 min with 6 workers. robots
  honoured; raw responses cached in `data/raw/uvm/` (gitignored); serval.uvm.edu never
  touched.
- 1,844 courses, 2,737 schedulable sections (2,313 arranged sections are never
  auto-scheduled). Attribute codes match the audit's. Modality: `schd` letters learned at
  ≥95% agreement; 249 sections stay unknown.
- Prerequisites come from the SOC comments (owner tip). The LLM parses them into flat node
  lists, rebuilt into trees in code: 1,109/1,183 usable, 74 held out as unknown.
- Report: `docs/uvm-data-report.md`. Capabilities feed validation rule 8.
- Gaps vs the done-bar: no Postgres load (no Docker here; JSON cache + in-memory parse
  instead, revisit in M9/M10). Past terms are unavailable from this source.
### M4 Solver, term mode ✅
- All 25 term-mode types encoded; hard → assumption literals, soft → 16/8/4/2/1×; minimal
  infeasible subset by deletion; ranked relaxations with schedules unlocked; top-5 by
  distinct course sets. 29 tests incl. 6 infeasible cases with known minimal sets.
- [x] real solve for the owner's state: 5 Spring 2027 schedules with CHIN 4200 (Track 3),
      CS 3920, ECON 1400, HST 1440 + a distinct gen ed, nothing before 10:30, 12–16 credits.
      The verbatim example is refused: CS 3050 is already in progress.
### M5 Validation layer ✅
- Rule 0 (JSON Schema contract) + rules 1–8, 24 tests.
### M6 NL translator + eval ⏸ (STOP: owner reviews the eval set)
- `chat/` (`planner_chat`): the translator's system prompt is the full constraint-spec reference
  (packaged copy, drift-tested) plus output conventions. Context: target term, open
  requirements, programs, catalog (code — title), prior spec for modification turns.
  Structured output with `params_json` (the contract's free-form params can't be strict; a
  per-type union exceeds Gemini's limits). Decoded, then validated (M5).
- Eval: `evals/translator/` holds 50 utterances (`REVIEW.md` is the readable version). The
  context is a synthetic student + real UVM course titles. Scored on type / params /
  enforcement / weight ±1, alternatives for genuinely ambiguous asks, out_of_scope expected
  for 4. Cassettes are committed, and `chat/tests/test_eval_replay.py` replays them in CI.
- **Result (gemini-3.5-flash):** first run 47/50 (94%). After two general prompt clarifications:
  **50/50 recorded**. An unrecorded live check passed 28/29 before Gemini prepaid credits ran
  out (402).
- **Failure categories seen:**
  1. *Requirement-count semantics:* read `satisfy_requirement.count` as a number of courses
     ("both my humanities and social science" → count 2 on humanities alone). Fixed with an
     explicit prompt rule.
  2. *Over-inference:* "avoid Aslim for macro" also added include-macro. Fixed with an "add only
     what was asked" rule.
  3. *Enforcement inference on hedged requests:* "I'd rather keep it light, around 12 credits"
     → hard w3 instead of soft w2. **Recurs in the live run**: the one persistent weakness.
     Mitigation: the M9 chip UI shows inferred weights as adjustable sliders, and the
     restatement lets the student catch it.
- Translator model for chat: `gemini-3.5-flash` (the plan's cheap structured-output model).
### M7 CLI demo ⏸ (STOP: owner reviews the transcript)
- `planner chat --audit <pdf> [--term 2027SP] [--standing] [--fail] [--script file]`
  (`chat/src/planner_chat/session.py`). Each message is one Flash translator call (current spec
  as prior), then validation, solver and a templated reply. A constraint with a validation
  problem is left out with the reason, and the rest is solved. Rule-6 contradictions are
  shown as conflicts. Infeasible results give numbered fixes; replying with a number applies
  one with no LLM call, and course-scoped rules go with a dropped course. `/spec` lists
  requests. Out-of-scope asks are told and logged to `.planner/out_of_scope.jsonl`
  (gitignored).
- The plan's exact example query works on the real audit (transcript:
  `fixtures/private/transcripts/m7_transcript.txt`). The demo run cost 2–3 Flash calls,
  ~30K input tokens each (the full catalog is in context).
- Fixed from reading the transcript: arranged in-person sections without times (CS 4996
  Honors Thesis) are never auto-scheduled, only when named; dropping a course drops rules
  scoped to it (the restatement had said "macro" after macro was dropped); a soft default
  load preference of 12–16 inside the hard 12–19 (it had packed 19 credits).
- **Stress test (2026-11-24, owner asked for varied prompts).** 11 private scenarios, 23
  messages (`fixtures/private/transcripts/stress/`): vague asks, days off, work shifts,
  instructors, nicknames and typos, already-taken courses, requirement asks, online-only,
  questions, small talk, graduation planning, what-if-I-fail, conflicts, follow-up edits.
  What broke and what changed:
  - **Wrong answers.** Plan-mode specs went to the term solver with no load cap and returned
    31-credit "schedules". Now the chat refuses plan mode until M8. "Something with
    Professor Dion" said no section matched, but Dion teaches five courses: only
    requirement courses were eligible. A wanted instructor's courses now are too.
  - **Message kinds.** The translator now returns an internal `intent` (schedule /
    question / greeting / thanks) next to the spec. This is not a contract change. Questions
    are answered from the audit and catalog, with no re-solve: what's left, credits and
    standing, when a course meets and what it counts for, what if I fail an in-progress
    course (re-derives the state with `per_course` and re-solves, one-off), and instructor
    opinions (declined).
  - **Honest summaries.** The LLM's restatement is no longer shown. A templated "Working
    with: …" line is built from the validated spec (`planner_solver/describe.py`), so it
    can't claim a dropped rule. It had said "at most 3 classes" after that rule failed.
  - **Explanations.** Conflicts carry catalog facts ("CS 3920 requires senior standing
    (your audit says junior)", "CHIN 4200 meets MWF 12:00–12:50pm"). A single impossible
    request reads as one. The logged idea is built: a "Heads up" when hard rules exclude
    every course that could meet a bottleneck requirement (Fridays free → CHIN 4200). It is
    skipped when only a load cap is the cause.
  - **Validation.** Unknown instructors are caught with suggestions. "Taken" says how
    (completed / taking now / registered). One-sided ranges are completed from the
    defaults. Pydantic dumps never reach the student. Notes carry no internal ids.
  - **Defaults.** The full-time band stays unless a *hard* load is stated, since a soft
    "around 12–14" had silently removed the 12-credit minimum. A light workload aims for
    12–13 credits.
  - **Output.** 12-hour times. Three schedules, with 2–3 shown as swaps against schedule 1.
    One requirement line per course (labs no longer repeat it). Clarifying questions and
    "can't do yet" are said once and not carried into the next turn. Defaults are not
    sent back to the translator as if the student said them.
  - Translator prompt: intent rules, both range ends, instructor-without-course, prefer the
    course an open requirement names ("a Chinese class" had picked 1st-year Chinese). The
    translator also gets the student's in-progress courses. `params_json` with a stray
    trailing quote is accepted (an observed Flash slip); anything else is still rejected.
  - Eval re-recorded: **49/50 (98%)**. Re-recording cost 3 × ~313K input + ~10K output
    Flash tokens, and the stress runs ~29K input per message. Remaining miss: "around 12
    credits" → 12–14 (defensible; owner to judge in the eval review).
### M8 plan mode — deferred by the owner to a later version (2026-11-24)
- Findings kept for later: the audit's 120-credit total (95 earned + in progress) isn't a
  course requirement today, so a plan must add elective credits; class standing must be
  projected per term (UVM's credit thresholds couldn't be confirmed: the catalogue page
  returned 503); only Spring 2027 offerings are known.
### M9 web UI ✅ (plain styling; owner iterates on design in V2)
- `api/` (`planner_api`, FastAPI): `POST /api/sessions` (raw PDF body, read from a temp file
  and deleted), `POST /api/sessions/{id}/messages`, `DELETE /api/sessions/{id}/rules/{rule}`,
  `GET /api/sessions/{id}`. In-memory sessions, one lock each, one LLM gateway (and budget)
  per session. Session setup shared with the CLI (`planner_ingest/chat_setup.py`).
- `ChatSession.view()`: rules as chips, top-3 schedules with meetings and what each course
  counts toward, conflict + why + fixes, tap-to-answer questions, open requirements. The
  same facts as the text reply. Closing a chip drops that rule with no LLM call (a closed
  default stays closed). In the web, the chat reply points to the calendar instead of
  listing schedules.
- `web/`: upload screen; chat (left); canvas (right) with chips, schedule tabs, a Mon–Fri
  grid (online/no-time sections listed under it), course table, conflict panel with one-tap
  fixes, requirement list. Zod-parsed API responses. `make dev` runs both on :3000/:8000.
- Verified end to end in Chromium on the real audit (upload, schedules, chip removal,
  conflict + fix).
- Removed the solver's health-only FastAPI stub (superseded by `api/`).
- Seen, not fixed: CS 4996 F (Honors Thesis) has a meeting time and no prerequisite in the
  SOC data, so it can be auto-scheduled as a CS elective.
### M10 beta — not started

## Schema proposals (owner reviewed 2026-11-18)
- Approved and documented in the reference: `satisfy_requirement.distinct`, day codes R/U.
- Pending (owner asked what they mean; explained in chat): instructor polarity values,
  modality default.
1. **`satisfy_requirement.distinct` (bool, default false).** Worked example 1 ("English A2 …
   and *one other* course that fulfills any gen ed") implies the gen-ed course must be a
   different course from the A2 one. Today one course may satisfy both constraints:
   double-counting is legal in DegreeWorks. Proposal: an optional param to force distinct
   courses across the listed constraints.
2. **Day codes.** The reference uses "M","W","F","T" but never names Thursday. Implemented
   `R` = Thursday, `U` = Sunday (registrar convention). Proposal: state this in the reference
   so the translator emits `R`.
3. **`instructor_preference.polarity` values.** The reference shows only `"exclude"`.
   Implemented `"include" | "exclude"` (hard/soft comes from `enforcement`). Proposal:
   document the enum.
4. **`modality` without comparator/count.** Implemented as "every course in this format".
   Proposal: document that default.

## Decisions
- **Templated summaries over LLM restatements** (2026-11-24): every line the student reads
  comes from the validated spec, the solver, the catalog or the audit. The LLM classifies
  and translates only.
- **Soft default load 12–16** inside the hard 12–19 band, added by validation only when no
  load is stated (`uvm/capabilities.json` `preferred_credit_range`). My judgment, pending the
  owner: without it, degree-progress maximisation packed every schedule to 19 credits.
- **Model per task (measured 2026-11-18 on the owner's $5):**
  - *Audit extraction: Flash.* 2 calls, 19,415 in + 31,405 out tokens. Golden test green. Its
    own course list garbled "A+" as "A process" (4×), but courses come from the PDF parse, so
    the output is right and the validator flagged them.
  - *Translator: Flash.* 50/50 recorded (M6).
  - *Prerequisite parsing: Pro.* On a 25-course sample Flash cost 1,788 in + 8,369 out tokens
    but **dropped majors-only restrictions** (BUS 3310, BUS 3611) and grouped "A, B, or
    permission" as (A and B) or permission. Too permissive. The committed answer store means
    Pro only ever sees new/changed notes.
- **Derived UVM data is committed in `data/uvm/`** (term.json, note text, trees, review,
  answer store). Rebuilding Spring 2027 prerequisites takes 0 LLM calls.
- **Cost controls (2026-11-18, after $10 of credits went fast).** Root cause: the bulk
  prerequisite parse (1,183 courses) ran on Gemini **Pro**, **twice** (format change), with
  no sample run and no cap, plus hidden thinking tokens billed as output. Fixes:
  every call's token usage (incl. thinking) is recorded in the cassette and summarised per
  command; `LLM_MAX_LIVE_CALLS` (default 30) stops runaway jobs; the default model is
  `gemini-3.5-flash` everywhere, with Pro only when explicitly set; the bulk prereq parse uses
  low effort; `planner prereqs --sample N` checks cost and quality before a bulk run.
  **Rule going forward:** sample-run every bulk LLM job and report its cost before running it
  in full.
- **The translator omits credit_range unless a load is stated.** Validation adds the 12–19 default
  deterministically (the reference says "always emit one"; doing it in code is stricter).
- **Owner (2026-11-18, latest):** degree requirements come before extra classes unless a class
  is explicitly requested. A course may count toward several requirements but is never taken
  twice. Default credit load: 12–19 (owner-confirmed; `uvm/capabilities.json`).
- **Bottlenecks first:** a requirement that only one or two courses can serve this term gets 3×
  progress weight (e.g. CHIN 4200, Track 3's last course, one section). This is a term-level
  stand-in until plan mode reasons across terms.
- **Bug fixed:** single SOC attributes come as plain text, not `<li>`; 332 courses had lost
  their attributes (175 → 507 with attributes). ECON 1400 is S1.
- **Owner (2026-11-18, later):** senior seminar counts 1 credit toward the 6-credit CS elective
  bucket (a partial contribution). Any course titled "Senior Seminar" requires senior standing,
  and it **blocks** (`uvm/owner_rules.py`). Defaults approved: instructor polarity
  include/exclude; modality without a count means every course. Fall 2026 is not needed.
- **Standing is strict**: below the required standing blocks the course. The audit's words
  are used ("03 - Junior"); `planner solve --standing senior` lets the student state their
  standing for the target term. Blocked courses name the real reason.
- **Progress, not coverage**: targets carry the still-needed amount and unit. The solver's
  tie-break rewards progress capped at the need. Each course line says what it counts toward
  ("… (1 of 6 credits)"), or that it was requested but counts toward nothing open.
- **Owner (2026-11-18):** a one-time scrape of Spring 2027 is OK, as fast as reasonable.
  Prerequisites are in the SOC comments.
- **Prerequisite trees are flat node lists from the LLM**: unrolled depth-3 schemas exceeded
  Gemini's limit. A tree with only `unparsed` parts is used (those parts evaluate as
  unknown); ambiguous/malformed ones are held out and marked unknown, never "none".
- **Requirement targets come from DegreeWorks' "N Classes/Credits in …" lines** (prefix
  optional, subject carried forward, ranges, wildcards, attributes, `Except` exclusions),
  falling back to the extracted rule. Only leaf requirements are targets.
- **Standing comes from the audit's words** ("03 - Junior"), never inferred from credits.
- **Output says "counts toward"**: one course may count for several requirements (CS 3920 is
  both Senior Seminar and inside CS 3000:3990). Whether UVM allows that double-count is
  DegreeWorks logic we can't see; listed under Open questions.
- **Owner choices (2026-11-17/18):** provider Gemini (billing on). Target Spring 2027, product
  term-agnostic. In-progress courses count as passed. CS 3050 is in progress (counts as taken).
  For majors with tracks, only the followed track matters.
- **req_ids are rendered into the LLM input**; the model must return one requirement per id.
  Any id it omits gets a targeted follow-up call (max 2). Fixes Pro dropping duplicated
  track rows.
- **Choice groups are detected from DegreeWorks' wording** ("Choose from 1 of the following")
  as well as `any_of`. The LLM encoded the Chinese track group as `unparsed`.
- **Review queue** = anything the validator caught + low-confidence requirements still to be
  planned. Completed ones are icon-confirmed (real audit: 25 items).
- **Golden compare:** `unparsed` + routed to review passes; a structured wrong unit fails.
- **Validator caps unparsed confidence at 0.6** (the prompt's rule; Gemini ignored it).
- **Solver:** compactness is an objective term only (not a yes/no rule). difficulty_load is
  a labelled estimate (level digit + lab). A course needs one section per component (LEC/LAB).
  Prerequisites are three-valued: permission/standing/unparsed → "unknown" → allowed with a
  warning, never silently "met".
- **Validation:** near-miss course codes are rejected with suggestions, never auto-corrected.
  Including an already-taken course is an error.
- Earlier decisions (still valid): structure-derived req_ids; courses_taken rebuilt from the
  PDF rows; per-school icon colors (blue = in progress); summary allow-list (no
  name/NetID/advisors to the LLM); rule depth 2; Gemini via its OpenAI-compatible endpoint.

## Open questions
- Exclusive vs shared course counting between requirements of the same major (see
  "counts toward" above).
- Next.js 14 advisories (last 14.x is 14.2.35): decide before the M10 deploy.
- No Docker daemon in this container: compose is unexercised.
- Preregistered-course marker unknown (none on this audit).

## out_of_scope requests discovered
- Multi-term planning / "can I graduate by …" (M8).
- Instructor ratings ("is Professor Hu a good teacher?", "who grades easiest?"): no data.
- Same schedule as a friend; exams in the same week; building (Votey Hall); section size
  (UVM publishes no caps).

## Log
- **2026-11-24 (owner bug + edit flow).** Bug: asking for 15 credits, then closing that chip,
  gave a 31-credit plan. A stated load replaces the full-time band, and closing it removed
  the only credit cap (the solver then adds every course that counts toward a requirement).
  Fix: closing a chip re-validates what's left, so the band comes back; the band itself
  (`default_credits`) can be changed but not closed (the web shows ✎, not ✕). The old test
  that closed the band now closes the soft preferred load instead (owner reported the old
  behavior as the bug).
  Owner: asking for one more class shouldn't rebuild everything. When a turn only adds
  courses and a plan is on screen, the chat now offers numbered choices (no LLM to pick):
  add it to that plan, swap out one class they didn't ask for, or rebuild. Each option is
  pre-solved with the plan's other sections pinned (term data restricted + internal
  include_course pins; no schema change) under every request, and says what it gives up
  (missed preferences, requirements it stops helping). The web sends the plan on screen.
- **2026-11-24 (plan feedback).** Owner: highlighted "counts toward" lines didn't show
  requirement progress, and the wish list didn't say which requests were met. The view now
  carries, per schedule, `missed_rules` (the solver's soft_missed) and `progress` (what the
  plan adds to each open requirement: courses + planned amount), plus `conflict_ids`. The web
  shows requests as a checklist (ticked / crossed out "Plan A couldn't fit this one" / "!"
  clash) and a "Degree progress" section with hand-drawn bars filled per course; "covered!"
  only when the audit states an amount needed. Double counting stays an open question, so the
  page says the audit decides it.
- **2026-11-24 (UI theme).** Owner asked for a hand-drawn school-planner look instead of Bauhaus:
  ruled paper, Caveat/Patrick Hand fonts, wobbly pen outlines (SVG displacement filter on a
  pseudo-element so text stays crisp), highlighter sticky notes per course, spiral binding,
  divider-tab catalog. Styling only; behavior unchanged.
- **2026-11-24 (UI redesign).** Owner asked for a calendar-first layout in a Bauhaus style:
  pull-out course catalog (left), weekly calendar (center), assistant chat (right). Added a
  deterministic catalog search (`ChatSession.catalog`, `GET /api/sessions/{id}/catalog?q=`):
  matches every word against code/title/instructor; no query lists what counts toward open
  requirements; status taken/blocked/check from the prereq tree. No LLM; "+ Add" sends
  "Add <code> to my schedule" through the normal chat pipeline. Fixed two tests that read docs
  without UTF-8 (failed on Windows). 239 Python + 6 web tests green.
- **2026-11-24 (Windows).** Owner is on Windows; `make`/`export` don't exist there. Added `.env`
  loading (`planner_llm/envfile.py`, real env vars win), `.env.example`, root `npm run
  setup|dev|test` (concurrently runs API + web). Fixed Windows bugs: every file read/write
  now names UTF-8 (Windows defaults to cp1252 and would crash on "›"/"–"); temp-dir cleanup
  tolerates a still-open PDF handle.
- **2026-11-24 (M9).** Web app: FastAPI over ChatSession + Next.js page (upload, chat,
  chips, weekly grid, conflicts with one-tap fixes). M8 deferred by the owner. 235 Python +
  4 web tests green.
- **2026-11-24 (M7 hardening).** Stress-tested the chat with 23 varied messages on the real
  audit and fixed what broke (see M7). 228 Python + 2 web tests green; eval 49/50.
- **2026-11-18 (M6).** Built the translator + 50-utterance eval: 94% → 100% recorded with
  gemini-3.5-flash. Gemini credits ran out during the live stability check.
- **2026-11-18 (later).** Owner approved a one-time scrape. Built the polite fetcher (6 workers,
  ~5 min), parser, LLM prerequisite parser, bridge, templated printer and `planner` CLI. Real
  Spring 2027 solve works. 156 tests green.
- **2026-11-18.** Paid tier unlocked Gemini Pro. Re-recorded; fixed omissions with req_id-guided
  extraction + follow-ups. M1 done-bar met. M2 built (+ owner's track rule). M3 source
  discovery found the ToS prohibition → blocked. M4 solver and M5 validation built on
  synthetic data. 125 tests green.
- **2026-11-17 · M1.** Gemini provider; first real runs; validator caught quote/attribute issues.
- **2026-11-16 · M1/M0.** Layout pass, validator, golden tooling; scaffold.
