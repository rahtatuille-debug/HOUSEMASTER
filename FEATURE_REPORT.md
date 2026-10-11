# FEATURE_REPORT — five more student performance graphs (P-1 … P-5)

## 1. Summary

Five hand-drawn SVG charts, in the existing chart style and with no chart library or schema change:
- **P-1** subject trends over terms;
- **P-2** assessment-type breakdown;
- **P-3** marks through a term;
- **P-4** position over terms;
- **P-5** a strengths radar.

They appear on the Performance page (student scope; P-1 also for class, year group and school) and on the student
profile (P-1). Parents get P-1, P-3, P-5 and, only where report cards already show positions, P-4, all without
class comparisons.

The numbers come from the existing analytics and rankings code, so they agree with the page. Class comparisons
need at least 5 students. Every chart has a table and focusable points and works at 320 px. The JS bundle grows
by 5.7 KB gzipped.

## 2. Ground truth (established in Step 0, before any code)

**Branch base.** Both repos: every `claude/fix-*` and `claude/followup-*` branch is merged into the default
branch (backend `master` at `7d15d61`, frontend `main` at `2abdef2`). No PRs were open for this work. New branches
`claude/perf-graphs` start from those default-branch heads. (The staff sign-up link PRs, housemaster#52 and
housemaster-frontend#46, opened in the same session, are separate and not part of this work.)

**What a `Grade` has** (`gradebook/models.py`): `student`, `subject`, `term`, `score`, `max_score` (default 100),
`assessment_type` (nullable FK to the school's `AssessmentType`: `name`, `weight`, `order`) and `recorded_at`
(`auto_now_add`). **There is no assessment date.** P-3 therefore plots `recorded_at`, converted to the school's own
time zone (`School.timezone`, `students/localtime.school_zone`), and the axis says "when recorded".

**How averages are built today** (`reporting/analytics.SchoolGrades`, `gradebook/weighting.subject_percent`):
each mark is a percentage (score / max). Marks of one assessment type are averaged; the types are then combined
**by their weights**, using only the types that have marks (rescaled to 100%). Marks with no type count as one more
type with the mean weight of the others. A school with no types gets a plain mean. A student's term average is the
plain mean of their subject results; a group's average is the mean of its students' averages. The database
aggregates per (student, term, subject, type) (the E-2 fix); nothing loads every mark. The new series reuse
`SchoolGrades` and these functions, so they agree with the numbers already on screen.

**Level-based schools** (CBC and other scales). Every number is still a percentage underneath. The existing charts
plot 0–100% and label values with the level (`useWithLevel`, e.g. "69% · ME"); the spread chart counts students per
level (`SchoolGrades.bands`). The new charts follow the same rule: a percentage axis, with the level shown beside
every value and in every table.

**Who can see what.**
- Staff: `accounts.scoping.visible_students(user, ACADEMIC)` (teaching assignments and roles; admins and
  leadership see the whole school). The existing `/api/analytics/performance/` answers a student outside that scope,
  or one that doesn't exist, with the same `404 {"detail": "Student not found."}`. Class and year-group scopes answer
  out-of-scope with `403` and missing with `404` (existing behaviour, kept).
- Guardians (and student accounts, which share `GuardianStudentViewSet`): only their own linked children.
  Today they see every one of the child's marks (`score`, `max_score`, `subject`, `term`, `recorded_at` — **not**
  the assessment type), the child's own average per term (`profile.performance`), and, for terms with a
  **finalized** report, the term summary: subject percentages and levels, and for 8-4-4 only the stream and form
  positions. Class and year-group averages are deliberately withheld from parents ("built from other children's
  grades", `guardians/views.py`).

**Minimum-data rules that exist.** `School.support_min_marks` (default 3): marks a student needs in a term before
their average counts for support. `School.ranking_min_share` (default 0): share of the usual subjects a student
needs marks in to be ranked, else "Not ranked: incomplete marks (x of y subjects)". CBC learners are never ranked
(`rankings.UNRANKED`). Ties share a position (1, 2, 2, 4). **There is no small-class threshold**, so one named
constant is added: `MIN_COMPARE_STUDENTS = 5` (see `docs/CHARTS.md`).

**Baseline.** Backend: `reporting`, `accounts.test_isolation`, `guardians`, `approvals` — 241 tests OK.
Frontend (`main`): `npm ci` OK, 288 tests passed, build OK, `npm audit --omit=dev` 0 vulnerabilities.
Main bundle before: JS 825,944 B (204,046 B gzipped), CSS 68,338 B (13,296 B gzipped) — larger than the ~470 KB the
brief mentions.

**Demo data.** A local copy of the seeded demo school (HouseMaster Demo College, British / IGCSE 9–1 levels,
Africa/Nairobi, two assessment types "Classwork" 40 and "Assessment week" 60, 18 terms, 233,000 marks) in scratch
SQLite. No real pupils' data.

## 3. Items

| ID | Status | Commits (backend · frontend) | Tests added | Notes |
|----|--------|------------------------------|-------------|-------|
| P-1 | Done | `97935ea` · `2dc4189`, `fc7fab0` | backend `SubjectTrendsTests` (7), `ChartPermissionTests` (4), guardian `test_subject_trends_only_for_finalized_terms_and_no_class_line`; frontend `P-1 subject trends` (3), `LineChart options` (2), `PerformanceCharts.test.jsx` (1) | Default subjects: the 6 with the most terms of marks (or the viewer's last choice). `fc7fab0` fixes a mismatched scope/id request found in the browser check. |
| P-2 | Done | `30365c0` · `727d547` | backend `AssessmentTypeTests` (6), guardian `test_no_assessment_type_chart_for_parents`; frontend `P-2 assessment types` (2) | Staff only (parents' marks carry no type). Minimum = the school's `support_min_marks`. |
| P-3 | Done | `5f3bb79` · `e09e9ea`, `9b3dbcc` | backend `MarksInTermTests` (4), guardian `test_marks_without_assessment_types`; frontend `P-3 marks within a term` (2), term-order test (1) | Dates are `recorded_at` on the school's clock. No class comparison (see §6). `9b3dbcc` fixes the parent's default term. |
| P-4 | Done | `1918258` · `f3601d3`, `99fd517` | backend `RankTests` (6), guardian `test_ranks_only_where_parents_already_see_them`, opt-in `SlowChartTests` (1); frontend `P-4 rank over time` (2) | Shares `overall_positions` with the ranked tables. `99fd517` shows one group at a time (readability). |
| P-5 | Done | — (uses P-1's data) · `055bcda` | frontend `P-5 strengths radar` (3), `RadarChart geometry` (3), `parents` (1) | No backend change needed. |

Docs and this report: `docs/CHARTS.md`, `FEATURE_REPORT.md`, screenshots in `docs/feature-report/` (one commit).

## 4. API changes (all additive)

- **New** `GET /api/analytics/charts/?chart=subject_trends|assessment_types|marks|ranks&scope=student|class|year_group|school&id=&term=&subject=` (staff).
  - Same permission checks and answers as `/api/analytics/performance/`: an out-of-scope or missing student is
    `404 {"detail": "Student not found."}`; class and year group keep `403`/`404`; school is leaders only.
  - Only `subject_trends` takes group scopes (others answer `400`).
  - Response keys:
    - `subject_trends`: `terms`, `subjects[].points[] {term, term_id, student, class}` (or `average` for groups),
      `compare.min_students`, `grading`.
    - `assessment_types`: `term`, `subject`, `subjects`, `types[] {id, name, weight, student, marks, reason, class}`,
      `min_marks`, `weighted`.
    - `marks`: `term {id, name, start, end}`, `date_basis: "recorded"`, `time_zone`,
      `points[] {subject, assessment_type, percent, date, recorded_at}`, `outside_term`, `subjects`.
    - `ranks`: `ranked`, `reason`, `points[] {term, term_id, class|year_group|school: {position, of} or {position: null, reason}}`,
      `basis_note`.
- **New** `GET /api/guardian-students/<id>/charts/?chart=subject_trends|marks|ranks&term=` (parents and student
  accounts). Unknown or other child: the viewset's usual `404`. `assessment_types`: `404 "This chart isn't available."`
- **Changed, internal only:** `SchoolGrades` keeps a per-type mark count (no extra query). `overall_positions()` is
  factored out of `_student_rows` unchanged; the existing analytics, rankings and rank-basis tests pass untouched.
- No existing response changed. A comparison of `/api/analytics/performance/` (student, class, year group, school),
  the staff profile and the guardian profile on the same seed before and after gave byte-identical JSON, apart
  from one `last_login` timestamp that changes on every sign-in.
- The new frontend against an older backend: every new card catches the failed request and shows a quiet
  "Not available yet." (tested).

## 5. Verification

**Tests first (backend).** `reporting/test_charts.py` was written before the code: 32 tests, **26 failed, 6
passed** (the 6 that passed assert "not found / forbidden" and passed only because the URL didn't exist yet). After
the code: 32 passed. Each commit was checked on its own (`reporting`, `guardians`: green at every stage).
Frontend chart tests were written after the components (stated plainly). The two later fixes (`fc7fab0`, `9b3dbcc`)
each came with a test, and `fc7fab0`'s test was run against the old code and failed.

**Backend checks.**
- `reporting`, `accounts.test_isolation`, `guardians`, `approvals`: **274 tests OK** (1 skipped: the opt-in slow
  check).
- `makemigrations --check --dry-run`: **No changes detected**.
- `check --deploy --fail-level ERROR` with CI's production-like settings: **0 errors** (one existing warning,
  `security.W021`, HSTS preload).
- **Full backend suite: 1,262 tests OK** (3 skipped, including the opt-in slow check).

**Query counts.** Tests assert the count stays the same as subjects, terms, types and marks grow (P-1, P-2, P-3,
P-4). Opt-in check on **233,000 marks** (`HOUSEMASTER_SLOW_TESTS=1`, not run in CI):

| Chart | Queries | Time |
|-------|---------|------|
| subject_trends | 11 | 0.68 s |
| assessment_types | 12 | 0.58 s |
| marks | 8 | 0.02 s |
| ranks | 11 | 0.74 s |

**Frontend checks.** `npm ci` OK; **308 tests passed** (52 files); `npm run build` OK; `npm audit --omit=dev`:
0 vulnerabilities.

| Main bundle | Before (raw / gzip) | After (raw / gzip) | Change (gzip) |
|---|---|---|---|
| JS | 825,944 / 204,046 B | 846,032 / 209,769 B | +5,723 B (+2.8%) |
| CSS | 68,338 / 13,296 B | 68,831 / 13,425 B | +129 B |

**Browser check** (Playwright, Chromium; local build against the seeded demo in scratch SQLite):
- admin, teacher and parent at 320, 375 and 1280 px;
- every new chart renders, and every new chart card has a working "Show as table";
- **0 horizontal overflow** and **0 CSP violations** at every width.

| Who | New charts seen | Console errors |
|---|---|---|
| Admin | 5 (+ the existing 2) | 0 |
| Teacher | 5 (+ the existing 2) | 0 |
| Parent | 3 (trends, strengths, marks); no positions in a British school | 1: the existing, by-design `403` from `/api/me/` before the parent identity is found (also on `main`, before the change) |

For P-3 to show something realistic, the scratch copy's current-term marks were given spread-out recorded
dates (the seed records every mark at import time). This was the scratch database only.

Screenshots (fictional demo pupils):

| Before | After |
|---|---|
| ![before admin](docs/feature-report/before_admin_1280.png) | ![after admin](docs/feature-report/after_admin_1280.png) |
| ![before parent](docs/feature-report/before_parent_1280.png) | ![after parent 375](docs/feature-report/after_parent_375.png) |

More: `after_teacher_320.png`, and `after_admin_375_tables.png` (every chart switched to its table).

**Isolation, live on the running server.**
- Teacher (classes 7A, 7B, 7C, 8B, 9A) asking for a 13A student, and for an id that doesn't exist, on all four
  charts: both `404 {"detail": "Student not found."}`, identical.
- Parent asking for another child, and for a missing id: both
  `404 {"detail": "No Student matches the given query."}`, identical.
- Parent on the staff endpoint: `403`. Parent asking for assessment types: `404 "This chart isn't available."`
- Cross-school is covered by `test_teacher_outside_their_classes_and_other_schools_get_not_found` and
  `test_another_schools_admin_gets_not_found`.

**Secrets and personal data.** Both diffs were grepped for key-like strings (secret, token, API keys, private keys,
long hex) and for real-looking emails and Kenyan phone numbers. **Nothing found**; tests use `.test` and
`.example` addresses and fictional names.

## 6. Decisions where the brief left room

- **P-1 default subjects:** the six with the most terms of marks (ties alphabetical), so the default shows the
  subjects with a real trend. The viewer's own choice is remembered in `localStorage` (a per-viewer convenience).
- **Small-class threshold:** none existed, so one constant was added, `MIN_COMPARE_STUDENTS = 5`, counting students
  with marks in that subject, type or term (not class size). The existing Performance page's class averages are
  unchanged (it never had a threshold); only the new charts apply it.
- **P-2 minimum marks:** the school's existing `support_min_marks` (default 3) rather than a new constant. P-1 and
  P-5 apply no per-subject minimum, because the page already shows those values from any number of marks and the
  new charts must agree.
- **P-3 class comparison:** omitted. With no assessment date, "the same assessment" can't be identified
  unambiguously (two marks of one type on one day are indistinguishable), so the brief's rule says omit it.
- **What parents see:** the strictest reading of today's exposure.
  - Subject results only for terms with a finalized report (that's where the term summary shows them).
  - No class lines anywhere (withheld from parents today).
  - Marks without assessment types.
  - Positions only for 8-4-4 finalized report cards (stream and form, as printed).
  - Student accounts get the same as parents (they share the view).
- **P-4 school position:** for admins and leadership only (the only people who see whole-school ranks today).
- **P-4 display:** one group at a time (class by default), so the class isn't squashed by a school of hundreds.
- **LineChart:** extended once (gaps, markers, focusable points, date axis, other y scale), all off by default, in
  the P-1 commit, rather than split across P-1, P-3 and P-4.

## 7. Additional observations (not built)

- **Recorded dates:** every mark in the demo, and any school that imported history, has `recorded_at` at import
  time, so P-3 shows "N marks were recorded outside this term's dates" for past terms. A real assessment date on
  `Grade` would fix this, but it is a schema change (not made).
- **Small classes on the existing page:** the existing Performance page and staff profile show class averages
  even for tiny classes. Applying `MIN_COMPARE_STUDENTS` there would change shipped numbers; owner's call.
- **Class-scope denial shape:** the performance endpoint answers an out-of-scope class with `403` but a missing
  class with `404`, which tells a teacher a class exists. The new chart endpoint copies this for consistency;
  making both `404` would be a small, separate change.
- **Bundle size:** the main bundle is 846 KB raw (210 KB gzipped), not ~470 KB as the brief expected. Splitting
  the Performance page (and charts) into its own lazily loaded chunk would cut the first load.
- The class heatmap, attendance against marks, a "where I sit in the spread" marker, print/PDF output and a
  parent-view redesign were deliberately not built.

## 8. Not verified

- Real devices (only Chromium emulation at 320/375/1280).
- Production-sized schools on Postgres (only SQLite with 233k marks).
- Real school data and real time zones other than Africa/Nairobi (the boundary tests use Africa/Nairobi).

## 9. Owner decisions needed

1. **Rank visibility for parents.** Today parents see positions only on finalized 8-4-4 report cards, so P-4 is
   shown to them only there. Showing positions to other parents would be a policy change.
2. **The small-class threshold** (`MIN_COMPARE_STUDENTS = 5` in `reporting/charts.py`): keep, change, or make it a
   per-school setting (that would need a migration).
3. Whether the existing Performance page should apply the same threshold (§7).
4. Merging both PRs and deploying (not done here).
