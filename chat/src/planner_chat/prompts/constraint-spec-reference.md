# Constraint Spec v0.1 — Reference

Companion to `constraint-spec.schema.json`. This is the document you hand to the LLM (in the system prompt) and to yourself when writing the solver.

---

## The two design decisions worth understanding

**1. There is no separate "hard" and "soft" section.** Every constraint is one object with an `enforcement` field. This matters because almost any constraint can be either: "no 8am classes" is hard for some students and a strong preference for others. One flat list means the LLM's job is uniform (extract → assign enforcement + weight), and infeasibility handling is natural: relax soft constraints by ascending weight, and if still infeasible, report which *hard* constraints conflict.

**2. Every constraint carries provenance.** `source_text` is the span of the user's message it came from. This powers the restatement UI (editable chips: tap "no classes before 10:30" to change it), makes bug reports readable, and means you never have to guess why a constraint exists.

---

## Weight conventions

`weight` is 1–5, and it does double duty:

- On **soft** constraints: the coefficient in the objective function. Normalize in the solver (e.g. weight 5 = 16×, 4 = 8×, 3 = 4×, 2 = 2×, 1 = 1× — powers of two keep a single weight-5 preference from being outvoted by a pile of weight-1s).
- On **hard** constraints: not in the objective, but used to *order relaxation suggestions* when infeasible. When nothing satisfies everything, you suggest dropping the lowest-weight hard constraint first.

`weight_source` tells the UI whether to ask:

| value | meaning | UI behavior |
|---|---|---|
| `stated` | user said importance explicitly ("I really can't do mornings") | trust it |
| `inferred` | LLM guessed from phrasing ("I'd rather not…" → 2, "I need…" → 5) | show as adjustable chip |
| `default` | nothing to go on, schema default used | show as adjustable chip |
| `user_confirmed` | user answered a `weight_check` question | locked |

**Suggested inference table for the LLM:**

| user phrasing | enforcement | weight |
|---|---|---|
| "must", "need", "can't", "absolutely" | hard | 5 |
| "I want", "make sure" | hard | 4 |
| "prefer", "ideally", "if possible" | soft | 3 |
| "would be nice", "I'd rather not" | soft | 2 |
| mentioned in passing, no modifier | soft | 1 |

---

## Clarification protocol

The LLM can ask questions, but asking is a cost — don't interrogate people. Rules:

- **Never ask more than 2 questions at once.** Prefer 1.
- **Default to `blocking: false`** — solve with your best guess, show results, and ask alongside. "Here are 5 schedules. Quick check: how important is the 10:30 rule, 1–5? If it's a 3 or below I can show you some better options."
- **Only block** when the request is genuinely unsolvable as stated (e.g. user named a course that doesn't exist, or asked for "a gen ed" when four different buckets are open and the choice changes everything).
- Use `kind` to route: `weight_check` → tappable 1–5; `ambiguity` → tappable options; `missing_info` → free text; `tradeoff` → present after solving.

Good clarification: *"You said 'avoid Smith' — just for macro, or any class?"*
Bad clarification: *"What is your preferred minimum gap between classes in minutes?"* (nobody knows; pick a default of 10 and let them adjust.)

---

## Constraint type reference

`data_dependency` column flags what might not exist at a given school. Anything marked ⚠️ needs a graceful fallback ("I can't filter by class size at your school yet").

### Content — what courses

| type | params | notes |
|---|---|---|
| `include_course` | `{ "course": "CS 3200" }` | specific course must be in the result |
| `exclude_course` | `{ "course": "MATH 220" }` | never suggest this course |
| `satisfy_requirement` | `{ "req_ids": ["GENED_HUM","GENED_SOC"], "count": 1, "distinct": false }` | **the disjunction workhorse.** "any one of my open gen eds" = all open req_ids, count 1. `distinct` (optional, default false): when true, the course(s) used here may not be the same course(s) used for any other `satisfy_requirement`, as in "one *other* course that fulfills a gen ed". Without it, one course may count for several requirements (double-counting is legal) |
| `course_attribute` | `{ "attribute": "writing_intensive", "count": 1, "comparator": "at_least" }` | attributes come from the catalog (honors, WI, service-learning) ⚠️ |
| `level_distribution` | `{ "level": 4000, "comparator": "at_most", "count": 2 }` | "no more than two 4000-levels" |
| `subject_limit` | `{ "subject": "CS", "comparator": "at_most", "count": 3 }` | avoid a term that's all one department |
| `difficulty_load` | `{ "target": "light" \| "moderate" \| "heavy" }` | ⚠️ **no real data in V0.** Proxy = weighted mix of course level, credit hours, lab presence. Always label output as an estimate. Later: derive from your own users' reported workload |

### Load

| type | params | notes |
|---|---|---|
| `credit_range` | `{ "min": 12, "max": 16 }` | always emit one; default to the school's full-time band |
| `course_count_range` | `{ "min": 4, "max": 5 }` | some students think in courses, not credits |

### Time

Day codes: `M` Monday, `T` Tuesday, `W` Wednesday, `R` Thursday, `F` Friday, `S` Saturday,
`U` Sunday.

| type | params | notes |
|---|---|---|
| `no_earlier_than` | `{ "time": "10:30", "days": ["M","W","F"] }` | omit `days` = all days |
| `no_later_than` | `{ "time": "17:00", "days": ["F"] }` | |
| `free_day` | `{ "day": "F" }` | |
| `free_block` | `{ "day": "T", "start": "14:00", "end": "17:00", "label": "work shift" }` | **high value, underrated** — jobs, athletics, clubs, commute. Probably your most-used constraint after time windows |
| `max_days_on_campus` | `{ "count": 3 }` | commuters care intensely |
| `max_consecutive_classes` | `{ "count": 2, "days": ["M","W"] }` | back-to-back cap |
| `gap_between_classes` | `{ "min_minutes": 15, "max_minutes": 120 }` | min = walking/eating time; max = no dead 4-hour holes |
| `compactness` | `{ "direction": "compact" \| "spread" }` | usually soft; "compact" minimizes total campus time |

### Section-level

| type | params | notes |
|---|---|---|
| `instructor_preference` | `{ "name": "John Smith", "polarity": "exclude", "course": "ECON 2020" }` | `polarity`: `"exclude"` (avoid them) or `"include"` (want them). **`course` is optional but usually present** — "avoid Smith" almost always means for one class. If omitted, applies globally. Needs fuzzy name matching against section data |
| `modality` | `{ "format": "online" \| "in_person" \| "hybrid", "comparator": "at_most", "count": 2 }` | ⚠️ schedule data usually has this; verify at your school. Without `comparator`/`count`, every course must be in that format ("online classes") |
| `section_size` | `{ "max_enrollment": 40 }` | ⚠️ needs seat-cap data; common in schedule of classes |
| `campus` | `{ "campus": "Main", "polarity": "only" }` | multi-campus schools |
| `travel_time` | `{ "min_minutes_between_campuses": 30 }` | pairs with `campus`; prevents impossible back-to-backs |
| `open_seats_only` | `{ "value": true }` | ⚠️ needs live seat counts. Enormously useful during registration week, and the reason to poll seat data frequently then |

### Labs

| type | params | notes |
|---|---|---|
| `max_consecutive_labs` | `{ "count": 1 }` | your "no back-to-back labs" — trivial in CP-SAT |
| `max_labs_per_day` | `{ "count": 1 }` | |

### Plan mode only

Invalid in `mode: "term"` — reject at validation.

| type | params | notes |
|---|---|---|
| `target_graduation_term` | `{ "term": "2029SP" }` | the anchor of plan mode |
| `credits_per_term` | `{ "min": 12, "max": 16, "terms": ["2028FA"] }` | omit `terms` = applies to all |
| `term_availability` | `{ "summer": true, "winter": false }` | willingness to use non-standard terms |
| `reserved_term` | `{ "term": "2028SP", "reason": "study abroad", "max_credits": 0 }` | study abroad, co-op, internship, medical leave |
| `add_program` | `{ "program_id": "MINOR_CS", "action": "explore" }` | the counterfactual engine — "what if I add a CS minor" |
| `front_load_prereqs` | `{}` | soft; prefer plans that clear prereq chains early, preserving future flexibility |
| `balance_difficulty` | `{}` | soft; avoid one brutal term ⚠️ (same proxy caveat as `difficulty_load`) |
| `keep_option_open` | `{ "program_id": "MAJOR_BIO" }` | for undecided students: don't foreclose this path |

---

## Worked example 1 — your original query

> "Build me a plan for next semester that fulfills my English A2 credit where I take software engineering, macroeconomics, and one other course that fulfills any of my general ed requirements. Make sure no classes are before 10:30am. For macroeconomics I want to avoid having Professor John Smith."

```json
{
  "spec_version": "0.1",
  "mode": "term",
  "target_term": "2027SP",
  "restatement": "Next semester: software engineering, macro (not with Smith), one English A2, and one more gen ed — nothing before 10:30.",
  "constraints": [
    { "id": "c1", "type": "include_course", "params": { "course": "CS 3200" },
      "enforcement": "hard", "weight": 5, "weight_source": "stated",
      "confidence": 0.9, "source_text": "I take software engineering" },

    { "id": "c2", "type": "include_course", "params": { "course": "ECON 2020" },
      "enforcement": "hard", "weight": 5, "weight_source": "stated",
      "confidence": 0.9, "source_text": "macroeconomics" },

    { "id": "c3", "type": "satisfy_requirement",
      "params": { "req_ids": ["ENGL_A2"], "count": 1 },
      "enforcement": "hard", "weight": 5, "weight_source": "stated",
      "confidence": 0.95, "source_text": "fulfills my English A2 credit" },

    { "id": "c4", "type": "satisfy_requirement",
      "params": { "req_ids": ["GENED_HUM", "GENED_SOC", "GENED_NAT"], "count": 1, "distinct": true },
      "enforcement": "hard", "weight": 4, "weight_source": "stated",
      "confidence": 0.85, "source_text": "one other course that fulfills any of my general ed requirements" },

    { "id": "c5", "type": "no_earlier_than", "params": { "time": "10:30" },
      "enforcement": "hard", "weight": 5, "weight_source": "stated",
      "confidence": 0.95, "source_text": "Make sure no classes are before 10:30am" },

    { "id": "c6", "type": "instructor_preference",
      "params": { "name": "John Smith", "polarity": "exclude", "course": "ECON 2020" },
      "enforcement": "hard", "weight": 4, "weight_source": "stated",
      "confidence": 0.9, "source_text": "avoid having Professor John Smith" },

    { "id": "c7", "type": "credit_range", "params": { "min": 12, "max": 16 },
      "enforcement": "hard", "weight": 3, "weight_source": "default",
      "confidence": 1.0, "source_text": "" }
  ],
  "clarifications": [],
  "out_of_scope": []
}
```

Note `c4`: "any of my general ed requirements" expands into the student's *currently open* gen-ed buckets, pulled from their parsed audit. The LLM doesn't invent these — they're injected into its context from the database.

---

## Worked example 2 — vague request with clarification

> "I want a chill semester, nothing too early, and I need to keep Tuesday afternoons free for work."

```json
{
  "spec_version": "0.1",
  "mode": "term",
  "target_term": "2027SP",
  "restatement": "Lighter load, later starts, Tuesday afternoons blocked off for work.",
  "constraints": [
    { "id": "c1", "type": "difficulty_load", "params": { "target": "light" },
      "enforcement": "soft", "weight": 4, "weight_source": "inferred",
      "confidence": 0.6, "source_text": "I want a chill semester",
      "data_dependency": "estimated" },

    { "id": "c2", "type": "credit_range", "params": { "min": 12, "max": 14 },
      "enforcement": "hard", "weight": 3, "weight_source": "inferred",
      "confidence": 0.6, "source_text": "chill semester" },

    { "id": "c3", "type": "level_distribution",
      "params": { "level": 4000, "comparator": "at_most", "count": 1 },
      "enforcement": "soft", "weight": 3, "weight_source": "inferred",
      "confidence": 0.5, "source_text": "chill semester" },

    { "id": "c4", "type": "no_earlier_than", "params": { "time": "10:00" },
      "enforcement": "soft", "weight": 3, "weight_source": "inferred",
      "confidence": 0.5, "source_text": "nothing too early" },

    { "id": "c5", "type": "free_block",
      "params": { "day": "T", "start": "12:00", "end": "17:00", "label": "work" },
      "enforcement": "hard", "weight": 5, "weight_source": "stated",
      "confidence": 0.8, "source_text": "keep Tuesday afternoons free for work" }
  ],
  "clarifications": [
    { "question": "What counts as 'too early' for you?", "kind": "ambiguity",
      "constraint_id": "c4", "options": ["9am", "10am", "11am", "noon"],
      "blocking": false },
    { "question": "Are your Tuesday shifts noon–5, or a different window?",
      "kind": "ambiguity", "constraint_id": "c5",
      "options": ["noon–5", "1–5", "all afternoon and evening"], "blocking": false }
  ],
  "out_of_scope": []
}
```

Both clarifications are non-blocking: solve with the guesses, show schedules, ask alongside. That's the difference between a product that feels sharp and one that feels like a form.

---

## Validation rules to enforce in code

Before anything reaches the solver:

1. Every `course` string matches a real course code (fuzzy-match first, then reject).
2. Every `req_id` is one of *this student's* requirement IDs.
3. Plan-only types rejected in term mode and vice versa.
4. `target_term` present iff `mode = "term"`.
5. Per-type param validation (zod/pydantic) — the JSON Schema deliberately leaves `params` loose; do the real checking here.
6. Contradictions caught early where cheap: `no_earlier_than 14:00` + `no_later_than 12:00` → don't waste a solve.
7. Any constraint with `confidence < 0.7` and no matching clarification → auto-generate a `weight_check` or `ambiguity` question.
8. Constraints whose `data_dependency` isn't available at this school → drop, and add to `out_of_scope` so the user is told honestly.

---

## Extending this

When a request doesn't fit, it lands in `out_of_scope`. Review that log weekly and sort by frequency. Promote recurring items into real types. Things I'd expect to show up early:

- "same schedule as my friend" (social — probably never build, but revealing)
- "avoid classes right after my commute"
- "I want Professor X specifically, whichever course they teach"
- "leave room for a 400-level I haven't picked yet"
- "no exams in the same week" (needs final exam schedule data)
- "prioritize classes that count toward both my major and minor" (double-counting optimization — actually high value)

That last one is worth watching for. Double-counting across programs is one of the hardest things students do by hand, and it's a natural fit for the solver.
