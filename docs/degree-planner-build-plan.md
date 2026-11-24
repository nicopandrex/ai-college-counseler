# Degree Planner: V0 → V1 Build Plan (v2)

**V0** = everything you can build and launch with zero university permission, at your own school, this year.
**V1** = what changes the day you sign your first department/university pilot.

**Companion files in this package — these are live artifacts, not examples:**
- `constraint-spec.schema.json` — the machine-readable contract between the LLM and the solver (33 constraint types, term + plan modes). Use it directly with structured outputs.
- `constraint-spec-reference.md` — per-type parameters, weight conventions, the clarification protocol, validation rules, and two fully worked examples. This doc goes *into the LLM's system prompt* and is also your solver implementation spec.

The core idea threading through everything: **the LLM never does math or invents facts.** It translates language into instances of the constraint schema and explains verified results. A deterministic solver working over verified data does all the actual reasoning. This is your correctness story, your demo story, and your fundraising story.

---

# PART 1 — V0: No Contract Required

## What V0 must prove

1. You can turn a student's own DegreeWorks audit + the public catalog into a correct, machine-readable model of their degree (ingestion works).
2. A solver over that model produces schedules and multi-year plans a smart student agrees with (reasoning works).
3. Students at one school actually use it during registration season and come back (demand works).

If all three are true, you have a fundable seed story and leverage for a university conversation. Nothing else in V0 matters.

## Step 0 is already done: the constraint schema

The highest-leverage design work — enumerating what the system can reason about — is captured in the two companion files. Before building anything, read the reference doc end to end and do one exercise: **write out 20–30 real registration requests** (yours, your friends', overheard complaints) and check each one against the schema. Requests that fit cleanly confirm the design. Requests that don't go into a running `out_of_scope` list — that list is your roadmap, and maintaining it is a standing weekly habit from now until forever.

Design decisions already locked in (don't relitigate them mid-build):
- One flat constraint list; every constraint has `enforcement` (hard/soft) + `weight` (1–5) + `weight_source` + `confidence` + `source_text` provenance.
- Weights do double duty: objective coefficients for soft constraints, relaxation-ordering for hard ones.
- Clarifying questions are first-class (`clarifications` array) and **default to non-blocking**: solve with best guesses, ask alongside results, max two questions.
- Out-of-schema requests are surfaced honestly and logged (`out_of_scope`), never silently faked.

## Phase 0: Validation Week (before product code)

Three throwaway experiments:

**1. Can you parse your own audit?** Download your DegreeWorks audit (the saved HTML parses better than PDF if available). Run it through Claude using the Component 1 prompt below. Check output against reality *line by line* — you are the ground truth. Then repeat with 3–5 friends in different majors (group rules, "3 of the following," credit minimums, and catalog-year differences all stress different Scribe patterns).

**2. Can you get section data?** Find the public schedule of classes. Check: days/times, instructor names, seat counts, **modality flags** (online/in-person — needed for the `modality` constraint), **enrollment caps** (needed for `section_size`), and whether past semesters are visible (needed to infer fall-only/spring-only patterns). Open browser dev tools → Network tab; many schools have a JSON API behind the page. Coursicle covering your school is a strong signal the data is accessible.

**3. Can you get the catalog?** Public catalog with prerequisites, gen-ed lists, and **course attributes** (writing-intensive, honors — these power `course_attribute`). Check whether prereq text is structured or prose, and whether past catalog years are archived (they almost always are).

While you're at it, note which schema constraint types your school's data can't support yet, and record that in your config as `data_dependency` availability — the validation layer drops unsupported constraints and tells users honestly instead of pretending.

## Architecture in plain language

Five boxes:

1. **Ingestion** — turns audits, catalogs, and schedules into clean data in a database.
2. **The degree graph** — the database: courses, prereq trees, requirements, sections, offering patterns, and each user's state.
3. **The solver** — consumes a constraint spec (schema instance) + the user's state, returns provably valid schedules/plans, or a minimal infeasible set explaining why none exist.
4. **The chat layer** — LLM that converts natural language into schema instances, and solver output back into friendly English.
5. **The canvas UI** — weekly calendar grid + four-year plan view that chat manipulates, with the restatement rendered as editable constraint chips.

Data flows one direction: language → spec → validation → solver → results → language. The LLM touches only the ends. The schema is the waist of the hourglass.

## Recommended stack

- **Frontend:** Next.js 14 + TypeScript + Tailwind (same as your internship-prep app). Vercel.
- **Backend:** Next.js API routes for CRUD; a small **Python FastAPI service** for the solver (OR-Tools is Python; separate service so a multi-second solve never blocks the app).
- **Database:** Postgres (Supabase or Neon free tier). Relational queries are non-negotiable here.
- **Solver:** Google **OR-Tools CP-SAT** — free, industrial-grade, timetabling is its textbook use case.
- **Validation:** zod (TS side) + pydantic (Python side), both generated from / checked against `constraint-spec.schema.json`. The JSON Schema deliberately leaves `params` loose; per-type validation lives here (see "Validation rules" in the reference doc).
- **LLM:** a strong model for ingestion (batch, accuracy-critical, cost-irrelevant); a cheap model with structured outputs for chat translation (high volume, schema-constrained). Your Gemini token-budgeting work from FinalDraft transfers directly.
- **Auth:** school-email verification (`@youruni.edu`).

## Component 1: Audit + transcript ingestion

**What it does:** student uploads their DW audit → structured record of (a) completed courses with grades/credits, (b) every requirement block with rule + status **+ a stable `req_id`**, (c) catalog year, programs, applied exceptions. Those `req_id`s are what `satisfy_requirement` constraints reference, so they must be deterministic across re-uploads (hash of block title + catalog year works).

**How:** deterministic text extraction (`pdfplumber`, no vision model needed — see below) → LLM structuring into a strict JSON schema → deterministic validation pass (credit sums, course codes exist, no requirement both complete and incomplete) → low-confidence fields flagged for the user to confirm, never silently accepted. The full extraction prompt is in `audit-extraction-prompt.md`.

**Confirmed on a real UVM audit:** DegreeWorks PDFs have a real text layer — no OCR/vision step needed. Two things matter for extraction quality:
1. **Use `page.extract_tables()`, not raw `extract_text()`, for the requirement blocks.** Default text extraction reads left-to-right by vertical position and scrambles two-column layouts — a row label like "Total Credit Requirement" ends up spliced mid-sentence into the adjacent "Still needed" paragraph. `extract_tables()` keeps cells grouped correctly since it's structure-aware, not reading-order-based.
2. Fall back to `extract_text()` only for non-tabular content (page headers, the summary block at the top).

```python
import pdfplumber

def extract_audit_text(pdf_path: str) -> str:
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        # join non-empty cells; keeps label/value pairs together
                        chunks.append(" | ".join(c for c in row if c))
            else:
                text = page.extract_text()
                if text:
                    chunks.append(text)
    return "\n".join(chunks)
```

Feed this output — not raw `extract_text()` — into the extraction prompt. Add a cheap validation heuristic before that: if a known requirement-block heading (e.g. "Total Credit Requirement") appears mid-sentence rather than at the start of a line in the extracted output, that page needs the table-extraction path, which is now the default above.

Reserve a vision-model fallback (Gemini Flash is cheapest) for the rare case where a page has zero extractable text — a scanned/photographed upload rather than a native export.

**Critical gap found and closed: status icons are invisible to both `extract_text()` and `extract_tables()`.** DegreeWorks draws its complete/incomplete/info indicators as colored vector shapes (`page.curves`), not text characters or images — so neither extraction path above captures them, even though they're the single most important signal in the document (whether a requirement is done). Confirmed on the real UVM audit:

- Green fill `(0.0, 0.502, 0.302)` → complete
- Red stroke `(0.8314, 0.1569, 0.1569)`, no fill → incomplete
- Blue fill → informational note (not a real requirement — e.g. "students are required to take a diversity course")

All icons sit in a narrow left-margin column (`x0 < 60`) at a `top` y-coordinate matching their adjacent text row. This is a **third deterministic extraction pass**, run alongside table/text extraction, joined by vertical position:

```python
def extract_row_statuses(page, margin_x=60, y_tolerance=3):
    """Classify each left-margin icon by color, return [(top_y, status), ...]."""
    COLOR_MAP = {
        (0.0, 0.502, 0.302): "complete",
        (0.8314, 0.1569, 0.1569): "incomplete",  # appears as stroke, not fill
    }
    statuses = []
    for c in page.curves:
        if c['x0'] >= margin_x:
            continue
        color = c.get('non_stroking_color')
        if color in COLOR_MAP:
            statuses.append((c['top'], COLOR_MAP[color]))
        elif c.get('stroking_color') in COLOR_MAP:
            statuses.append((c['top'], COLOR_MAP[c['stroking_color']]))
        elif isinstance(color, tuple) and color not in (None,):
            statuses.append((c['top'], "info"))  # blue / other = informational icon
    return statuses

def nearest_status(row_top, statuses, tolerance=5):
    candidates = [s for s in statuses if abs(s[0] - row_top) <= tolerance]
    return candidates[0][1] if candidates else None
```

Join this to each table row's vertical position (pdfplumber table cells carry bbox info) to get a per-row `icon_status`, and pass that alongside the extracted text into the extraction prompt — it's a strong independent confirmation signal for the `status` field the LLM outputs, and it catches the "info, not a real requirement" case ("students are required to take a diversity I course") that has no other textual marker. Treat a mismatch between `icon_status` and what the LLM inferred from surrounding text as an automatic low-confidence flag.

**Caveat to verify, don't assume:** this exact RGB triplet is specific to UVM's DegreeWorks color theme. Ellucian lets institutions customize these colors, so recalibrate the `COLOR_MAP` per school during onboarding (a 5-minute check against one sample audit) rather than hardcoding it globally.

**Why this stays deterministic rather than moving to a vision model, explicitly:** it's tempting to reach for a vision model "to be safe" once you know status is icon-encoded, but that's the wrong trade here. Locating the icons is the hard part and vision doesn't help with that — you'd still need curve position to crop to the right region. Color-matching three known RGB values is the easy part, and it's exact: zero failure rate, free, instant. Swapping it for a probabilistic model replaces a solved problem with a new failure mode (misclassification) on the single most consequential field in the document — the one the solver's whole correctness story depends on. Vision has two narrow, legitimate roles instead:

- **Per-school onboarding, once:** when adding a new institution, feed one sample audit's rendered page to a vision model to bootstrap that school's `COLOR_MAP` (Ellucian lets schools theme these colors) instead of manually reverse-engineering it. Low stakes — a human confirms one config value, not thousands of live classifications.
- **Per-row fallback, rarely:** if a curve's color doesn't match any known entry in `COLOR_MAP` (an unrecognized icon), crop just that row and send it to a cheap vision model rather than silently guessing a status. Everything else stays on the deterministic path.

This is the same principle as the rest of the architecture: deterministic wherever an exact answer exists, AI only where it genuinely has to fill a gap — never as a blanket "safer" substitute for code that already works.

**Then a separate deterministic derivation step** (`derive_state`) converts the parsed record into the solver's student state. This is where **in-progress coursework is treated as satisfying** requirements and prerequisites by default (`in_progress_policy: "assume_pass"`), while the underlying distinction stays preserved in the record. That flag is the counterfactual engine — "what if I fail this class" is the same function with one course flipped — and it's why the parser must not collapse in-progress into complete. Requirements met only by in-progress work are marked `provisionally_satisfied`; ones with minimum-grade rules carry `pending_grade_risk` so the UI can say "assumes you pass MATH 141 with a C or better."

**Build prompt (Claude Code, iterate on your real audits):**

> I'm building a parser that converts DegreeWorks degree audit documents (HTML and PDF exports) into structured JSON. Target schema: [paste — include a stable req_id per requirement block, derived from hashing block title + catalog year]. Here are 3 real anonymized audits: [paste]. Write a Python pipeline that: (1) extracts raw text/structure, (2) calls an LLM with an extraction prompt that outputs only schema-valid JSON and quotes the source line for every requirement (provenance), (3) runs deterministic validation (credit sums, course-code regex against a known course table, requirement-status consistency, req_id stability across re-parses of the same audit), (4) emits a confidence report of uncertain fields so the UI can ask the user to confirm those specific items.

**What you do by hand:** grade it. Spreadsheet of 20 real audits across majors, every requirement, parser output vs. truth. This eval set is real IP — treat it like a test suite and rerun it on every prompt/model change.

**Privacy from day one:** audits are students' own records — them sharing with you is fine, but write a plain-English privacy policy (no selling data, delete on request, minimal retention), encrypt at rest, never train on or expose individual data. A university IT team will eventually read this policy; write it for them.

## Component 2: Catalog ingestion

**What it does:** per-semester batch producing: every course (code, title, credits, **attributes**, **level**), prereq logic as a boolean tree, gen-ed bucket membership, cross-listings. Levels and attributes feed `level_distribution`, `subject_limit`, and `course_attribute` constraints.

**Build prompt:**

> Write a scraper + parser for my university's catalog at [URL]. Stage 1: polite crawl (rate-limited, cached, robots.txt-respecting), raw HTML stored per course. Stage 2: extract code, title, credits, level, attributes, description, prereq text. Stage 3: LLM converts prereq prose into this boolean-tree JSON: [AND/OR/min-grade/concurrent-allowed/standing/instructor-permission node types]. Validation pass flags trees referencing nonexistent courses; ambiguous prereqs go to a manual-review queue file.

**What you do by hand:** clear the ambiguous queue ("or instructor permission," "junior standing," "or equivalent" — model these as explicit node types, students need to see them). Hand-verify the gen-ed lists completely: small, high-stakes, rarely changing.

**Legal caution:** scraping your own public university site is generally low-risk (public data, no login wall), but read the ToS, scrape gently, never hammer during registration week, and prefer any published data files/APIs if they exist.

## Component 3: Section + offering data

**What it does:** current term: every section's days/times/instructor/seats/modality/campus. Historical: 4–6 past terms to infer offering patterns (fall-only, alternate-year) — simple counting, no LLM, stored as *predictions with confidence* because the UI must say "offered every fall for 6 straight years" is a pattern, not a promise. During registration week, poll seat counts frequently — that's what powers `open_seats_only`, one of your highest-value registration-time constraints.

**Professor ratings:** don't scrape RateMyProfessors (ToS-prohibited, lawsuit-shaped). `instructor_preference` needs only *names*, which your section data has. Let your own users rate/flag professors later; that dataset compounds and belongs to you.

## Component 4: Constraint validation layer

New explicit component now that the schema exists. Sits between the LLM and the solver; implements the 8 validation rules from the reference doc:

1. Course codes fuzzy-matched against the real course table, else rejected.
2. `req_id`s must belong to *this student's* parsed audit.
3. Plan-only constraint types rejected in term mode and vice versa.
4. `target_term` required iff term mode.
5. Per-type param validation via zod/pydantic.
6. Cheap contradiction checks before solving (e.g. `no_earlier_than 14:00` + `no_later_than 12:00`).
7. Any constraint with `confidence < 0.7` and no matching clarification → auto-generate a `weight_check`/`ambiguity` question.
8. Constraints whose `data_dependency` isn't available at this school → dropped + moved to `out_of_scope` so the user is told honestly.

This layer is boring and it is where trust lives. Build it with the same test rigor as the solver.

## Component 5: The solver

**Two modes** (mirroring the schema's `mode` field):
- *Term mode:* select sections satisfying all hard constraints, maximize the weighted soft objective (weight → coefficient via powers of two: 5→16×, 4→8×, 3→4×, 2→2×, 1→1×, per the reference doc). Return top-5 structurally distinct schedules.
- *Plan mode:* assign remaining requirements to terms through `target_graduation_term`, respecting prereq ordering, offering patterns, `credits_per_term`, `reserved_term`s, and `term_availability`.

**The feature that wins:** each constraint's `id` becomes a CP-SAT **assumption literal**. On infeasibility, extract the minimal infeasible subset and return those ids — the chat layer turns them into "your 10:30 rule and the Smith exclusion can't coexist; here are three relaxations, ranked." Relaxation suggestions are ordered by ascending `weight` on the conflicting hard constraints. Build this from day one; it's the screenshot-and-share moment.

**Build prompt:**

> Using Python and OR-Tools CP-SAT, build a course-scheduling solver consuming constraint specs conforming to the attached constraint-spec.schema.json, with per-type semantics as defined in the attached constraint-spec-reference.md. Inputs: (1) student state (completed courses, open requirements keyed by req_id with satisfying-course sets), (2) catalog graph (courses, prereq boolean trees, credits, levels, attributes), (3) section data (meeting patterns as intervals, instructor, seats, modality, campus). Implement term mode (top-5 structurally distinct solutions, soft-constraint objective with power-of-two weight scaling) and plan mode (term assignment under prereq ordering, offering patterns, per-term credit bounds, reserved terms). Wire every constraint's `id` to an assumption literal; on infeasibility return the minimal infeasible subset as machine-readable constraint ids. Implement all 33 constraint types from the schema; for `difficulty_load` and `balance_difficulty` use the documented proxy (level + credits + lab presence) and tag outputs as estimates. Include a test suite of hand-built tiny examples with known-correct answers, including at least three deliberately infeasible cases with known minimal conflict sets.

**What you do by hand:** sanity-check output against your own degree and friends'. "Valid but dumb" results (18 credits of 400-levels) mean a missing constraint or bad default — feed it back into the schema. This iteration is the product taste; it can't be delegated.

## Component 6: The chat layer

**What it does:** user message + history + student state → schema instance → validation → solver → results → natural-language answer + updated canvas.

**Rules that keep it honest:**
- LLM output is *only* a schema instance (use structured outputs / JSON mode with `constraint-spec.schema.json`). The `restatement` field renders as editable chips before/alongside solving — the user's chance to catch mistranslations.
- The weight-inference table and clarification protocol from the reference doc go verbatim into the system prompt ("must/need/can't" → hard w5; "prefer/ideally" → soft w3; max 2 questions; default non-blocking; good/bad question examples included).
- Every concrete fact in answers (times, professors, requirement coverage) is templated from solver output. The LLM writes connective tissue, tradeoff explanations, and turns minimal-infeasible-sets into ranked relaxation options.
- Out-of-schema asks → honest "can't filter by that yet" + logged to `out_of_scope`.

**Build prompt:**

> Build the NL→constraint translation layer targeting constraint-spec.schema.json. System prompt inputs: the full constraint-spec-reference.md (types, params, weight-inference table, clarification protocol), the student's open requirements (req_ids + names), valid course codes and instructor names for fuzzy matching, and few-shot examples covering: disjunctive requirements ("any gen ed" → satisfy_requirement with multiple req_ids), course-scoped instructor exclusion, free_block extraction from mentions of jobs/practice/commute, vague-load requests ("chill semester" → difficulty_load + credit_range + level_distribution with inferred weights and low confidence, per worked example 2 in the reference), and modification turns ("actually cap it at 15 credits" → diff against prior spec). Output: strict schema instance including restatement, clarifications (non-blocking by default), and out_of_scope. Then build the response layer: solver results → answer where every schedule fact is data-inserted; infeasibility → name the conflicting constraints by their source_text and present 2–3 relaxations ranked by how many schedules each unlocks. Include an eval harness: 50 test utterances with expected specs, scored automatically on constraint-type match, param match, enforcement, and weight within ±1.

**What you do by hand:** write the 50 eval utterances from real registration scenarios (the 20–30 from the Step-0 exercise seed this), then grow the set from production logs. Write the voice: sharp older student, not compliance document.

## Component 7: The UI

Chat panel + live canvas: weekly grid (term mode), semester-by-term plan (plan mode). Chat changes → animated diffs on the canvas. **Constraint chips**: the active spec rendered as tappable chips (from `source_text` + params), each adjustable — weight sliders appear on chips whose `weight_source` is `inferred`/`default`, locked once `user_confirmed`. Requirement sidebar with provenance links ("satisfies A2 — source: your audit, line ..."). Clarification questions render as tap-to-answer options (from the `options` array), shown alongside results when non-blocking. Compare view for 2–3 schedules. One-tap share image — campus growth runs on screenshots.

Use the frontend-design skill when building; demo polish is cheap and disproportionately persuasive with both investors and advisors.

## Component 8 (stretch, only after 1–7 are solid): the codegen escape hatch

For requests that recur in `out_of_scope` but aren't schema-worthy yet: let the LLM emit calls against a **restricted helper API** (`forbid_adjacent(course_set, minutes)`, `require_free_block(day, start, end)` …) — never raw solver access. Sandboxed (separate process, time limit, no network/filesystem), labeled "experimental rule" in the UI with a plain-English interpretation the user confirms, and every use logged. Recurring generated rules get promoted into the schema. This is the flywheel: codegen is requirements discovery, the schema absorbs what proves durable. Do not build this before the schema path handles the common 90%.

## What only you can do in V0

1. **Ground-truth verification.** You are QA. Every launch-blocking bug is "the parser or solver was confidently wrong."
2. **The Step-0 exercise + weekly out_of_scope review.** The schema evolves on evidence, not vibes.
3. **Recruit 20 beta users across majors** before launch — engineering + humanities + a transfer + a double major. Transfers and double majors find bugs fastest.
4. **Time launch to registration.** Demand exists ~3 weeks/semester. Ship 4 weeks before registration opens; measure retention at the *next* cycle.
5. **Distribution:** major GroupMe/Discords, QR-code table, "send me your audit and I'll show you your whole degree" DMs. Campus products spread through group chats faster than subreddits.
6. **Privacy policy + visible provenance.** "Verify with your advisor" plus tap-any-requirement-to-see-source. Provenance-as-UI *is* the disclaimer done well.
7. **Instrument:** signups, parse success rate in the wild, specs generated, solves run, clarifications answered, chips edited (mistranslation rate!), out_of_scope frequency table, and the money metric: **% of users returning the following registration cycle.**

## V0 cost + timeline

- ~$0–50/mo (free tiers; ingestion is cheap batch, chat uses a cheap schema-constrained model).
- Part-time pace: Step-0 exercise + Phase 0 ~1 week; ingestion 3–4 wks; validation layer + solver 3–4 wks; chat + eval harness 2–3 wks; UI 3–4 wks; beta + polish 3 wks. **A semester to launch**, timed to registration.
- Sequencing: read reference doc → Step-0 exercise → Phase 0 → ingestion → validation+solver → chat → UI. The demo that matters first runs in a terminal.

---

# PART 2 — V1: The First University Contract

V1 is not "V0 with more features." It's a second product (advisor + institution) grafted onto proof the first one worked. Everything below assumes V0 has real usage.

## Who you actually sell to first

Not the provost, not central IT. First contract is almost always:

- **A single department or college advising office** with discretionary budget — often signs $5k–25k without full procurement.
- **The advising/student-success office**, if they carry innovation budget.
- **Your own school**, using the unfair advantages: hundreds of their students already on it, professors who know you, an entrepreneurship center to broker intros. First customers are relationship-shaped.

**Pitch built from V0 data:** "X hundred of your students already use this; here's the bottleneck course adding an average of N terms; we'd like to give your advisors the dashboard." You're selling visibility into plan/intent data that exists nowhere else in the institution, plus advisor throughput.

**Pilot structure:** one semester, one department, **paid** ($5–15k — free pilots die of neglect), 3 pre-agreed success metrics (% of advisees with an approved plan; advisor hours saved/week self-reported; off-track students flagged who received intervention), and a pre-agreed expansion price if metrics hit. That pre-agreement is the difference between a pilot and a dead end.

## What you build for V1

**1. Advisor dashboard.** Caseload list, computed status per student: plan missing / stale / infeasible / off-track (plan misses graduation target or student deviated from approved plan). Risk sorting. Click-through to any student's live plan and constraint chips — advisors seeing *why* a student's schedule looks odd ("works Tuesdays, commuter, max 3 days on campus") is itself a selling point.

**2. Approval workflow (your retention moat).** Student builds plan → "Send to advisor" → advisor sees a diff vs. last approved plan → one-click approve or inline comment → student notified. Keeps liability with the human by design, keeps both sides dependent on you, and keeps plans *current* — which protects the aggregate data.

**3. Aggregate demand reports.** "214 students plan ECON 301 for Spring '28; historical capacity 160." Bottleneck analysis per department. PDF/spreadsheet export, because these reports get forwarded upward, and forwarded reports are how you get the campus-wide meeting.

**4. Official data feeds replacing scraping.** With a contract: DegreeWorks API access (needs DW 5.0.4+, their IT configures services-API access; budget a quarter; Coursedog's public integration docs are the reference for what to request) and/or SIS (Banner/Ethos) for enrollment + sections. Scraped pipeline becomes fallback. Official feeds also upgrade several `data_dependency` flags from "estimated" to "reliable" — seat counts, modality, attributes — which visibly improves the student product and kills the "is your data right?" objection.

**5. SSO + roles.** SAML/Shibboleth or CAS, advisor/student/admin roles, audit logs of who viewed which student.

## The compliance gauntlet (start early, this order)

- **FERPA:** as a vendor you're designated a "school official." DPA with data minimization, breach terms, no secondary use. A few hours of a higher-ed-savvy lawyer; don't wing it.
- **HECVAT:** download HECVAT Lite *now* and build toward it — it's a free checklist of what campus IT will demand (encryption, access control, backups, incident response, hosting).
- **SOC 2:** rarely required for a departmental pilot, increasingly required campus-wide. Start Type I only when a deal demands it (~$10–20k + months via Vanta/Drata).
- **Accessibility:** build to WCAG 2.1 AA from V0 (semantic HTML, keyboard nav, contrast) so the VPAT is paperwork, not a rewrite. Public universities are legally required to care.
- **Insurance:** cyber liability + E&O before signing (~$1–3k/yr at your size); their contract will require it.

## Sales reality, plainly

- Warm departmental pilot: 3–6 months first-meeting-to-signature. Campus-wide: 9–18. Budget cycles: schools commit fall spend in the preceding winter/spring.
- The question you'll get every time: "how is this different from DegreeWorks SEP / Stellic / whatever Ellucian says is coming?" Memorized answer: *SEP is a manual whiteboard — no solver, no natural language, no aggregate view. Stellic is a rip-and-replace of your audit system requiring a full implementation project. We're a layer your students adopted on their own, working with what you already own — live in weeks, and we bring plan data nobody else has.*
- The champion sells internally, not you. Arm one director of advising with a deck, a live demo on aggregate/anonymized data from their own students, and ROI in their boss's units: time-to-degree, retention, advisor throughput.
- Expect the "shadow IT" objection to students uploading audits pre-contract. Answers: it's the student's own record; here's the privacy policy and HECVAT posture; and the contract is precisely what converts this into sanctioned infrastructure.

## Yourself vs. help (V1)

Yourself: all product, the champion relationship, the pilot metrics report, HECVAT answers.
Help: legal (DPA/FERPA review), SOC 2 when triggered, and one real advisor co-designing the dashboard. Befriend an advisor at your school during V0; monthly coffee. This person is worth more than any feature.

## Fundraising note

The clean seed story this plan produces: "N students at [school] adopted organically; M% returned the next registration cycle; chip-edit rate shows the NL layer works; we signed a $Xk paid pilot on the strength of demand data; the wedge is student-acquired intent data no incumbent has." Raise, if you raise, after the retention number exists — until then every piece is executable by one person + AI tools, which also means minimal dilution.

---

## Prompt library (all for Claude Code sessions; attach both companion files to every session)

1. **Audit parser** — Component 1 prompt (stable req_ids, provenance quoting, confidence report).
2. **Catalog scraper + prereq boolean trees** — Component 2 prompt (attribute/level extraction, manual-review queue).
3. **Solver** — Component 5 prompt (all 33 types, assumption literals, minimal infeasible subsets, difficulty proxy, adversarial infeasible tests).
4. **NL→spec translator + eval harness** — Component 6 prompt (reference doc in system prompt, 50-utterance eval, ±1 weight scoring).
4b. **derive_state** — "Write a deterministic function converting parsed audit JSON into solver student state. Params: in_progress_policy (assume_pass default | assume_fail | per_course with a failed_courses list), min_grade_pending_policy. Treat in-progress and preregistered coursework as satisfying prereqs, requirement coverage, and credit totals under assume_pass; mark such requirements provisionally_satisfied; tag min-grade requirements as pending_grade_risk; track earned vs earned_plus_in_progress credits separately; exclude preregistered courses from being proposed by the solver. Pure function, fully unit-tested, no LLM." 
5. **UI** — "Build a Next.js app with a chat panel and live weekly-calendar canvas rendering solver output. The active constraint spec renders as tappable chips built from each constraint's source_text and params; chips with weight_source inferred/default show a 1–5 weight slider; clarifications render as tap-to-answer options from their options arrays, non-blocking ones alongside results. Requirement sidebar items link to provenance. Compare view for up to 3 schedules; one-tap share image. Use [frontend-design skill / my design tokens]."
6. **Advisor dashboard (V1)** — "Advisor caseload dashboard: computed per-student status (plan missing/stale/infeasible/off-track), risk sorting, student detail with live plan + constraint chips + diff-since-last-approval, one-click approve with inline comments. Roles: advisors see only assigned students. Include an aggregate view: planned-demand counts per course per term vs. historical capacity, exportable to PDF/XLSX."
7. **Codegen escape hatch (Component 8, later)** — "Design a restricted helper API over the CP-SAT solver (named functions like forbid_adjacent, require_free_block — no raw model access). Build an LLM layer that maps out-of-schema requests to helper calls, executes them in a sandbox (subprocess, 2s timeout, no network/fs), returns a plain-English interpretation for user confirmation, and logs every generated rule with its user_text for schema-promotion review."

## Order of operations, one line

Read reference doc → 20–30 request exercise → Phase 0 validation week → ingestion → validation layer + solver → chat → UI → 20 beta users → registration-season launch → retention data → advisor friend → paid departmental pilot → official data feeds → aggregate reports → expand.
