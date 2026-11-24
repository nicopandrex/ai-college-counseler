# UVM data report (M3)

**Source:** UVM Schedule of Courses, `soc.uvm.edu` (CourseLeaf FOSE JSON API). Spring 2027
(`202701`) was pulled once on 2026-11-18 at 1 request/second, honouring robots.txt (none
on that host), per the owner's decision. Raw responses are cached under `data/raw/uvm/`
(gitignored) and never re-fetched.

**Not used:**
- `serval.uvm.edu`: robots.txt `Disallow: /`. It hosts the classic schedule and the
  historic enrollment files.
- `catalogue.uvm.edu`: resets connections from this cloud network.

UVM's website Terms of Use prohibit scrapers. The owner accepted a one-time pull; see
PROGRESS.md.

## What the data contains
- **Sections:** course code, section number, CRN, meeting days and times, instructor
  (initial + last name), open/closed status, and a schedule-type letter (`schd`).
- **Per course** (one details call): credits (variable credit → minimum), attributes with
  codes (match the audit's: S1, AH1–3, D1–2, WIL1–2, N1–2, QD, QR, SU, GC1…),
  instructional method, description. The class size is listed for one section per course
  only.
- **Prerequisites:** prose in each course's SOC comments (`clssnotes`); parsed by LLM into
  trees, with doubtful ones in `prereq_review.json`.
- **Not included:** campus, past terms (the SOC lists only Fall 2026 and Spring 2027).

## Constraint types: availability at UVM (feeds validation rule 8)

| type | status | notes |
|---|---|---|
| include/exclude_course, satisfy_requirement, credit_range, course_count_range | reliable | |
| course_attribute | reliable | attribute codes on every course |
| level_distribution, subject_limit | reliable | derived from course codes |
| no_earlier_than, no_later_than, free_day, free_block, max_days_on_campus, max_consecutive_classes, gap_between_classes, compactness | reliable | from meeting times; sections with no meeting time (online/TBA) never conflict |
| instructor_preference | reliable | names are "J. Smith" form; initial matching |
| modality | estimated | `schd` letters learned from each course's representative section (dominant meaning, ≥95% agreement); 249 sections stay unknown |
| open_seats_only | estimated | open/closed **as of the pull date**; no live seat counts |
| max_consecutive_labs, max_labs_per_day | reliable | lab sections identified by method |
| difficulty_load, balance_difficulty | estimated | proxy (level + lab), always labelled |
| section_size | **unavailable** | dropped → out_of_scope |
| campus, travel_time | **unavailable** | dropped → out_of_scope |
| plan-mode offering patterns | **unavailable** | needs ≥4 past terms; only Spring 2027 was pulled |

## Gaps that need the owner
1. **Prerequisite review queue:** trees the parser doubts (ambiguous, unparsed, malformed)
   are kept out of the solver until reviewed.
2. **Past terms** for offering patterns (M8) aren't in the SOC.
