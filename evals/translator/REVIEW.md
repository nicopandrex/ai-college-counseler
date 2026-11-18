# Translator eval set: owner review

50 requests a student might type, each with the constraint spec the translator should
produce. The student is synthetic. The courses are real UVM Spring 2027 entries.

**What to check:** is each expected answer what you'd mean? Is each weight right (hard 5 = must,
hard 4 = want, soft 3 = prefer, soft 2 = would be nice)? Add any requests real students would type.

Weights are matched within ±1. `a/b` means either is accepted. *Alternatives* are other answers
also accepted.

**u01**: “I need to take Senior Seminar next semester.”
  - → `include_course` (course=CS 3920) — hard w5
  - *alternative:* `satisfy_requirement` (req_ids=['CS_SENIOR_SEM'], count=1) — hard w5

**u02**: “Don't put me in Software Engineering.”
  - → `exclude_course` (course=CS 3050) — hard w5

**u03**: “I need one course that counts toward any of my open gen eds.”
  - → `satisfy_requirement` (req_ids=['GENED_S1', 'GENED_AH3', 'GENED_D1', 'GENED_WIL2', 'GENED_N2'], count=1) — hard w5

**u04**: “I need to knock out both my humanities and my social science gen eds this term.”
  - → `satisfy_requirement` (req_ids=['GENED_AH3', 'GENED_S1'], count=2) — hard w5

**u05**: “I want to make progress on my CS electives.”
  - → `satisfy_requirement` (req_ids=['CS_ELECTIVES'], count=1) — hard w4

**u06**: “I want macroeconomics, but not with Professor Rodrigues.”
  - → `include_course` (course=ECON 1400/ECON 2400) — hard w4
  - → `instructor_preference` (name=Rodrigues, polarity=exclude, course=ECON 1400/ECON 2400) — hard w4

**u07**: “Make sure one of my classes has the WIL2 attribute.”
  - → `course_attribute` (attribute=WIL2, count=1, comparator=at_least) — hard w4
  - *alternative:* `satisfy_requirement` (req_ids=['GENED_WIL2'], count=1) — hard w4

**u08**: “I want at most two CS classes.”
  - → `subject_limit` (subject=CS, comparator=at_most, count=2) — hard w4

**u09**: “I'd prefer no more than one 3000-level course.”
  - → `level_distribution` (level=3000, comparator=at_most, count=1) — soft w3

**u10**: “I want a chill semester.”
  - → `difficulty_load` (target=light) — soft w4
  - *may also add:* credit_range, level_distribution, course_count_range

**u11**: “I need to take Advanced Data Science and Algorithm Design and Analysis.”
  - → `include_course` (course=CS 3870) — hard w5
  - → `include_course` (course=CS 3240) — hard w5

**u12**: “I need my stats requirement done this semester.”
  - → `satisfy_requirement` (req_ids=['STATS'], count=1) — hard w5

**u13**: “Ideally I'd take History of China and Japan.”
  - → `include_course` (course=HST 1440) — soft w3

**u14**: “I want 15 to 16 credits.”
  - → `credit_range` (min=15, max=16) — hard w4

**u15**: “I need exactly four classes.”
  - → `course_count_range` (min=4, max=4) — hard w5

**u16**: “I'd rather keep it light, around 12 credits.”
  - → `credit_range` (min=12, max=12) — soft w2
  - *alternative:* `credit_range` (min=12, max=13) — soft w2
  - *may also add:* difficulty_load

**u17**: “I can't have any classes before 10:30.”
  - → `no_earlier_than` (time=10:30) — hard w5

**u18**: “I'd prefer not to have class after 4pm.”
  - → `no_later_than` (time=16:00) — soft w3

**u19**: “Keep Fridays free, I absolutely need that.”
  - → `free_day` (day=F) — hard w5

**u20**: “It would be nice to have Mondays off.”
  - → `free_day` (day=M) — soft w2

**u21**: “I work Tuesdays from 1 to 5, so I can't have class then.”
  - → `free_block` (day=T, start=13:00, end=17:00) — hard w5

**u22**: “I have practice Monday and Wednesday from 3:30 to 6 and I can't miss it.”
  - → `free_block` (day=M, start=15:30, end=18:00) — hard w5
  - → `free_block` (day=W, start=15:30, end=18:00) — hard w5

**u23**: “I can't do anything before 9 on Tuesdays and Thursdays.”
  - → `no_earlier_than` (time=09:00, days=['T', 'R']) — hard w5

**u24**: “Ideally no more than 3 days on campus.”
  - → `max_days_on_campus` (count=3) — soft w3

**u25**: “I'd rather not have more than two classes in a row.”
  - → `max_consecutive_classes` (count=2) — soft w2

**u26**: “Make sure I have at least 15 minutes between classes.”
  - → `gap_between_classes` (min_minutes=15) — hard w4

**u27**: “Ideally no huge gaps, nothing over two hours between classes.”
  - → `gap_between_classes` (max_minutes=120) — soft w3

**u28**: “I'd prefer my classes clustered close together.”
  - → `compactness` (direction=compact) — soft w3

**u29**: “I need Tuesday and Thursday afternoons free for my internship.”
  - → `free_block` (day=T, start=12:00, end=17:00/18:00) — hard w5
  - → `free_block` (day=R, start=12:00, end=17:00/18:00) — hard w5

**u30**: “I can't take evening classes.”
  - → `no_later_than` (time=17:00/18:00) — hard w5

**u31**: “I really want a class with Professor Dion.”
  - → `instructor_preference` (name=Dion, polarity=include) — hard w5

**u32**: “Avoid Professor Aslim for macro if possible.”
  - → `instructor_preference` (name=Aslim, polarity=exclude, course=ECON 1400/ECON 2400) — soft w3

**u33**: “I need every class to be in person.”
  - → `modality` (format=in_person) — hard w5

**u34**: “At most one online class, if possible.”
  - → `modality` (format=online, comparator=at_most, count=1) — soft w3

**u35**: “I need classes that still have open seats.”
  - → `open_seats_only` (value=True) — hard w5

**u36**: “I prefer small classes, under 30 people.”
  - → `section_size` (max_enrollment=30) — soft w3

**u37**: “No back-to-back labs, I can't handle that.”
  - → `max_consecutive_labs` (count=1) — hard w5

**u38**: “I can't take more than one lab in a day.”
  - → `max_labs_per_day` (count=1) — hard w5

**u39** (plan mode): “Plan out my remaining semesters so I graduate by Spring 2028.”
  - → `target_graduation_term` (term=2028SP) — hard w5

**u40** (plan mode): “I'm studying abroad in Fall 2027, so no classes that term.”
  - → `reserved_term` (term=2027FA, max_credits=0) — hard w5
  - *may also add:* target_graduation_term

**u41** (plan mode): “Across my remaining semesters, I can't take more than 15 credits in any term.”
  - → `credits_per_term` (max=15) — hard w5

**u42** (plan mode): “What would my plan look like if I added the CS minor?”
  - → `add_program` (program_id=MINOR_CS, action=explore) — hard/soft

**u43**: “Give me the same schedule as my roommate.”
  - → **out of scope**: can't be expressed, so it's logged and the student is told honestly

**u44**: “I don't want two exams in the same week.”
  - → **out of scope**: can't be expressed, so it's logged and the student is told honestly

**u45**: “Find me the professors who grade the easiest.”
  - → **out of scope**: can't be expressed, so it's logged and the student is told honestly

**u46**: “Put all my classes in Votey Hall.”
  - → **out of scope**: can't be expressed, so it's logged and the student is told honestly

**u47**: “Actually, cap it at 15 credits.”
  - *modifies:* `no_earlier_than` {'time': '10:30'}; `credit_range` {'min': 12, 'max': 16}
  - → `no_earlier_than` (time=10:30) — hard w5
  - → `credit_range` (min=12, max=15) — hard w4

**u48**: “Never mind about Fridays.”
  - *modifies:* `include_course` {'course': 'CS 3920'}; `free_day` {'day': 'F'}
  - → `include_course` (course=CS 3920) — hard w5

**u49**: “Actually 10 is fine.”
  - *modifies:* `no_earlier_than` {'time': '10:30'}
  - → `no_earlier_than` (time=10:00) — hard w5

**u50**: “Next semester I want senior seminar and macro but not with Professor Rodrigues, plus one other course for any of my gen eds. Make sure nothing starts before 10:30.”
  - → `include_course` (course=CS 3920) — hard w4
  - → `include_course` (course=ECON 1400/ECON 2400) — hard w4
  - → `instructor_preference` (name=Rodrigues, polarity=exclude, course=ECON 1400/ECON 2400) — hard w4
  - → `satisfy_requirement` (req_ids=['GENED_S1', 'GENED_AH3', 'GENED_D1', 'GENED_WIL2', 'GENED_N2'], count=1, distinct=True) — hard w4
  - → `no_earlier_than` (time=10:30) — hard w4
