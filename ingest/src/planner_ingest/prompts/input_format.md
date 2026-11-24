## Input format

The audit below was extracted deterministically from the PDF. It is in document order.

- `AUDIT SUMMARY` lists header fields as `Label: value`.
- `BLOCK [req_id: <id>] <title> [block status: <WORD>]` starts a requirement block. The
  indented lines under it are that block's header text. `BLOCK <title> [course listing]` is a
  listing of courses, not a requirement.
- `ROW [req_id: <id>] [icon: <status>] <label>` is one requirement row. `<status>` was read from the colored
  status icon DegreeWorks draws beside the row:
  - `complete`
  - `incomplete`
  - `in_progress`: the audit legend calls this "Complete except for in-progress classes"
  - `nearly_complete`: still incomplete
  - `prereq_needed`
  - `unknown`: an unrecognised icon

  The icon is the document's own status marker for that row, so base `status` on it.
  `[no icon]` marks a row that has no status icon, such as a list or a note.
- Indentation (two spaces per level) shows nesting. A row belongs to the nearest
  less-indented row above it.
- The indented text line under a ROW is that row's rule or still-needed text.
- `COURSE code | title | grade | credits | term` lines are course rows applied to the
  requirement above them. Credits in parentheses with grade `IP` mean in progress.
  `|| Satisfied by: ...` is the transfer-equivalence note for that course.

Every `[req_id: ...]` in the input is one requirement. Return exactly one requirement per
req_id, in document order, with `req_id` set to that id exactly; this replaces the req_id
generation rule above. Skip none of them, even when several rows read the same (alternative
tracks often repeat course rows). Courses under a `[course listing]` belong in
`courses_taken` only. The `ROW`/`COURSE` tags, `|` separators and `[...]` annotations are not
document text, so never put them in a `source_quote`.

Requirements counted by attribute designation (for example "1 course with a WIL1
designation" or "3 credits in courses with an AH1 designation") are `course_list` rules whose
`from` is DegreeWorks' own selector notation, `["@ @ with attribute = WIL1"]`, with
`has_wildcard: true`. Designations such as AH1, WIL1, D1, QD and SU are attributes, not
course codes. Never put a bare designation in `from`.

Each `from` entry is one course code or selector. DegreeWorks shortens lists by dropping a
repeated subject: "CHIN 1070 or 1012 or HST 1440" means `["CHIN 1070", "CHIN 1012",
"HST 1440"]`, and "CS 3000:3990" is a range kept as one entry. A rule with an exception clause
("Except ...") does not fit `course_list`, so use `unparsed`.
