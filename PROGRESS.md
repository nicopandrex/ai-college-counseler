# PROGRESS

Running log. Resume from **Current status**. Newest log entries at the top.

## Current status
- **Done:** M0, M1, M2, M5. M4 is done except its "real solve against UVM data" bar.
- **Blocked:** M3 (UVM data), on the owner's decision: UVM's website Terms of Use prohibit
  scrapers (see Blockers). M4's real solve, M7 and M8 depend on M3.
- **Next without the owner:** M6 (NL translator + eval harness). It needs no UVM data, and its
  50-utterance eval set needs owner review (a STOP).

## Blockers (need owner)
1. **UVM data source (M3).** UVM's Terms of Use
   (www.uvm.edu/compliance/website-privacy-policy/terms-use) say: "You agree, further, not
   to use … any engine, device, technique, software, tool, agent … (including without
   limitation browsers, spiders, robots, scrapers …) to navigate, access or search this
   Site, other than generally available third-party web browsers." Also,
   `serval.uvm.edu/robots.txt` is `Disallow: /`, and `catalogue.uvm.edu` resets
   connections from this cloud network. Sources found:
   - `soc.uvm.edu`: the current Schedule of Courses, a CourseLeaf "FOSE" app with a JSON
     API (`api/?page=fose`). No robots.txt.
   - `serval.uvm.edu/~rgweb/batch/…`: classic schedule + current/historic enrollment
     files (robots-disallowed).
   - `aisweb1.uvm.edu` (Banner course search), `catalogue.uvm.edu` (CourseLeaf catalog).
   Options for the owner: (a) ask the Registrar for permission or a data export (best,
   and aligned with V1); (b) the owner saves pages in their own browser (permitted by the
   ToS wording) and uploads them for a parser; (c) the owner decides the ToS doesn't apply
   to a low-rate personal tool. That's their call, not mine.

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
### M3 UVM data ⛔ blocked (see Blockers)
### M4 Solver, term mode ✅ (synthetic) / ⛔ real-data solve
- All 25 term-mode types encoded; hard → assumption literals, soft → 16/8/4/2/1×; minimal
  infeasible subset by deletion; ranked relaxations with schedules unlocked; top-5 by
  distinct course sets. 29 tests incl. 6 infeasible cases with known minimal sets.
- [ ] real solve against UVM data for the owner's state (needs M3)
### M5 Validation layer ✅
- Rule 0 (JSON Schema contract) + rules 1–8, 24 tests.
### M6 NL translator + eval — next
### M7 CLI demo (STOP) · M8 plan mode · M9 web UI · M10 beta — not started

## Schema proposals (batched for owner review; nothing changed in the contract)
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
- Next.js 14 advisories (last 14.x is 14.2.35): decide before the M10 deploy.
- No Docker daemon in this container: compose is unexercised.
- Preregistered-course marker unknown (none on this audit).

## out_of_scope requests discovered
_(none yet: the translator isn't built)_

## Log
- **2026-11-18.** Paid tier unlocked Gemini Pro. Re-recorded; fixed omissions with req_id-guided
  extraction + follow-ups. M1 done-bar met. M2 built (+ owner's track rule). M3 source
  discovery found the ToS prohibition → blocked. M4 solver and M5 validation built on
  synthetic data. 125 tests green.
- **2026-11-17 · M1.** Gemini provider; first real runs; validator caught quote/attribute issues.
- **2026-11-16 · M1/M0.** Layout pass, validator, golden tooling; scaffold.
