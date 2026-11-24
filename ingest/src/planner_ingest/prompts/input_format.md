## Input format

The audit below was extracted deterministically from the PDF. It is in document order.

- `AUDIT SUMMARY` lists header fields as `Label: value`.
- `BLOCK <title> [block status: <WORD>]` starts a requirement block. The indented lines under
  it are that block's header text.
- `ROW [icon: <status>] <label>` is one requirement row. `<status>` was read from the colored
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

Extract one requirement for every BLOCK and for every ROW that has an icon, in document order.
Skip none of them. The `ROW`/`COURSE` tags, `|` separators and `[...]` annotations are not
document text, so never put them in a `source_quote`.
