# FIX_REPORT: the ⚠ items from the known-gaps list

This file is the same on every fix branch, so merging the PRs in any order never conflicts on it.

## 1. Summary

All items A-1 to H were done in place: bugs fixed and gaps closed, with no new features.

**Where the work is:**
- **Branches.** Ten backend branches and six frontend branches, with one commit per item. Every item has a regression test that was seen failing first.
- **Admissions.** The admissions fixes are commits on the open admissions PRs (backend #14, frontend #12).
- **Stacked PRs.** Two backend PRs are stacked, because they share a migration chain or a counting helper.

**Verification:**
- **Integration run.** All branches merged locally in the planned order with no conflicts. On that merged tree:
  - full backend suite: 945 OK, plus 2 Postgres-only race tests run on a local Postgres;
  - frontend: 185 tests;
  - deploy check: no errors;
  - migrations apply and reverse on an empty database and on a seeded copy;
  - the pre-flight is proven to abort;
  - a browser smoke of the changed screens shows no page errors.
- **One isolation sweep** was added and found no leak.

**Blocked (owner):** GitHub-hosted runners stopped picking up CI jobs on 2026-10-05 around 20:00 UTC (H-13), so CI is not green on PRs #17 to #23 and frontend #14 to #17. The code was not the cause.

Nothing was merged or force-pushed, and production was not touched.

**Owner choices (2026-10-06).** The owner answered the open questions, and the follow-up work is in section 11:
- X-1 to X-4 are on #15 and FE #13;
- the Postgres CI job is #24;
- web push is #25 and FE #18.

## 2. Items

| ID | Status | PR (backend / frontend) | Commits | Tests | Notes |
|---|---|---|---|---|---|
| A-1 | Done | #15 / FE #13 | 01c5e28 / baa3b11 | boarding.test_safeguarding.MissingBoarderTests; boarding.test.jsx "A-1…" | Open absence per boarder, closed only by a person; backfill command |
| A-2 | Done | #15 / FE #13 | 7448ed3 / 185f6d7 | FinishedRollCallTests; "A-2…" | Lock + admin amend with reason; log has status codes only |
| A-3 | Done | #15 / FE #13 | bc13767, 2555f98 / e90e6e1 | HouseHistoryTests; students.test_demo_* ; "A-3…" | PROTECT + archive; demo resets clear boarding history first |
| A-4 | Done | #16 / — | 7870598 | reporting.test_report_class_stamp | Stamp once; admin correct-class (logged); "Class: not recorded"; certain-only backfill |
| A-5 | Done | #15 / FE #13 | 76012fd, 9726200 / 5aebe92 | ReleaseBedTests; "A-5…" | One `release_boarders` for every leaving path; unbedded list + profile flag |
| A-6 | Done | — / FE #13 | 37131ca, aa34337 | houseLabels.test.jsx | Copy only |
| B-1 | Done | #14 / FE #12 | 98a7a79 / 95ee5d5 | admissions.test_fixes.ConfirmEmailTests; admissions.test.jsx B-1 | Unconfirmed until email confirmed; hashed single-use token; console email backend locally |
| B-2 | Done | #14 / FE #12 | fcfeb14 / 7f38df7 | DuplicateTests, DuplicateRaceTests (Postgres) | Dedupe under a row lock; refuse re-enrolling an existing student |
| B-3 | Done | #14 / — | 7f4faa6 | ApplyLimitTests | Per-IP 30/h, per-email 5/h (silent), same answer always |
| B-4 | Done | #14 / FE #12 | c36cb37 / cbd911d | FamilyDataTests | Export + removal; retention off by default; health-notes design note |
| B-5 | Done | #14 / FE #12 | 0eacb46 / c48eaef | FormChecksTests, AdmissionNumberRaceTests (Postgres) | DOB/phone checks; age note; race-safe admission numbers; pre-flight migration |
| C-1 | Done | #17 / FE #14 | c4d1c03, 2c37484 / 3e62acc | support.test_fixes | Min marks/days, per-year pass mark, reopen on worsening, no "big drop" for new students |
| C-2 | Done | #18 | 16e1f18 | (documents) | DPA, DPIA, school notice, counsel Qs 15–16; export claim corrected |
| D-1 | Done | #17 / FE #14 | 91f2fa1 / 6df62aa | reporting.test_rank_basis; rankings.test.jsx D-1 | Basis per row; "not ranked: incomplete marks"; same rule on export and 8-4-4 card; design note |
| E-1 | Done | #19 / FE #15 | 5d048b4 / 64f9bec | students.test_paging; studentsPaging.test.jsx; api.test.js E-1 | Paged on request; server search/filters; pickers follow pages |
| E-2 | Done | #20 | e23cebd | reporting.test_school_aggregation (+ slow test) | Exact DB aggregation + per-request caching; numbers below |
| F-1 | Done | #21 / FE #16 | 8b72513, fb13af2 / fa49392 | timetable.test_fixes.UnstaffedTests | Deactivation lists lessons; unstaffed list |
| F-2 | Done | #21 / FE #16 | ed3dafc / 7853bd5 | OptionClashTests | Option changes report clashes |
| F-3 | Done | #21 / FE #16 | f7ff3ef / d03a934 | timetable.test.jsx F | Per-block override (frontend only); two design notes |
| G-1 | Done (fixed) | FE #17 | 6c19625 | offlineSafety.test.jsx G | Data could be lost silently, so fixed |
| G-2 | Checked | #22 | — | students.test_demo_large | Guard refuses with DEBUG off; scratch run wrote nothing |
| G-3 | Done | #22 | 132e6b9 | (documents) | Leave authority, notifications |
| H | Done | #23, #14 | 9b31cbb, c6c74ea | housemaster.test_isolation_sweep; admissions…AdmissionsIsolationTests | No leak found; mutation check proves the sweep catches one |

## 3. Stack and merge order

Merge in this order. Each PR's CI must be green on its head first (H-13).

1. **Admissions (#14 + FE #12).**
2. **#15 + FE #13:** boarding A-1, A-2, A-3, A-5, A-6.
3. **#16:** A-4.
4. **#17 + FE #14:** C-1, D-1. #17 is stacked on #14 (both add `students` migrations: 0015 there, 0016 and 0017 here). GitHub retargets it to master once #14 merges.
5. **#20:** E-2, stacked on #17 (it changes how mark counts are read).
6. **#18:** C-2 and owner actions (documents).
7. **#19 + FE #15:** E-1.
8. **#21 + FE #16:** F.
9. **#22 + FE #17:** G.
10. **#23:** H.
11. **#24:** the Postgres CI job (X-5).
12. **#25 + FE #18:** web push (X-6).

All of them were merged locally in this order. The one expected conflict is `students/privacy.py` between #14 and #15. Both add family-export sheets and JSON keys right after the Boarding sheet, and the fix is to keep both sides (admissions first). After #14 merges, merge master into #15 that way. Two route/import lines were moved on my own branches to avoid conflicts (9726200, fb13af2).

**Backend before frontend.** The frontend PRs tolerate an older backend: new fields are optional, and the Students page falls back to filtering on screen.

## 4. What changed for the owner

**Boarding**
- A missing boarder stays on Today until someone presses Found and records how it was resolved.
- Finished roll calls can only be corrected by an admin, with a reason.
- Houses with history can be archived, not deleted.
- Leaving, graduating, switching to day or deactivating frees the bed.
- Labels now say "Sports house" and "Boarding house".

**Report cards**
- The class on a report card no longer changes if it is sent back and finalised again.

**Admissions**
- Families confirm their email before the school sees anything.
- Copies are merged, and the form gives the same answer whatever happens.
- Applications are in the family export and removal tools.
- New students get an admission number.

**Support and rankings**
- Support suggestions need enough marks and attendance days, a dismissed suggestion returns if things get clearly worse, and the pass mark can be set per year group.
- Students with incomplete marks show "Not ranked: incomplete marks".

**Lists and timetable**
- The Students list loads 50 at a time.
- The Timetable shows unstaffed lessons.
- Changing options warns about clashes.

**Offline registers**
- A register kept offline no longer overwrites another teacher's marks.

**Steps for the owner:** before and after deploying, follow H-13 to H-17 in `docs/HUMAN_ACTIONS.md`.

## 5. Evidence

**Baseline.** Backend accounts, approvals, guardians and messaging: 301 OK. Frontend: 150 tests and a clean build.

**Red then green.** Every item's tests were run against the old code first and failed for the stated reason (commit messages), then passed.

**Integrated tree (all branches merged in order, never pushed):**
- `manage.py test --parallel 4`: Ran 945, OK (2 skipped: the Postgres race tests).
- Those 2 race tests on local Postgres 16: OK. Without the lock they fail 3 out of 3 times (B-2), and the admission-number race hits the constraint (B-5).
- `makemigrations --check`: no changes.
- `check --deploy --fail-level ERROR` with production-like settings: 0 errors (1 warning, `SECURE_HSTS_PRELOAD`, already there before).
- Frontend: 185 tests pass; the build is clean.

**Migrations**
- On an empty database: all forward, then reversed to before each new migration, then forward again.
- On a copy seeded with the large demo (233,000 marks): forward in 2.5 s; every new command's dry run printed counts only; reversed and forward again.
- B-5 pre-flight: on a scratch database with 3 students sharing number "42", the migration stopped with "school 1: 1 admission number(s) shared by 3 students. Nothing was changed." It applied once that was fixed, and reversed.

**E-1** (1,000 current students, SQLite):

| Request | Time | Size | Queries |
|---|---|---|---|
| Whole list (old shape, still served) | 0.156 s | 615 KB | 2 |
| One page of 50 | 0.015 s | 30 KB | 3 |

**E-2** (whole-school page, best of 3; output byte-identical before and after in every case):

| Data | Before | After |
|---|---|---|
| Demo, 233k marks (1 mark per type), SQLite | 1.11 s, 11 queries, 41.8 MB | 1.12 s, 11 queries, 44.5 MB |
| Same, Postgres 16 | 1.17 s | 1.14 s |
| About 4 marks per type (519k), SQLite | 2.27 s, 134.9 MB | 1.62 s, 47.5 MB |

On the demo, computing halved (0.78 s to 0.38 s) but loading rose (0.37 s to 0.62 s), because every group holds one mark. The win grows with the number of marks per type.

**Browser smoke** (headless Chromium; admin, teacher, parent and the public on the integrated build):
- Students: "Showing 50 of 1,000", then "Show 50 more" gives "100 of 1,000", and server search finds no match for a nonsense query.
- Boarding: Found resolves an absence and the list empties.
- Admissions: apply shows "Check your email"; a second identical application sends no email; the confirm link shows the reference; reusing it is refused; the admin then sees the application.
- Teacher: "Showing 50 of 168".
- The parent home loads.
- 0 page errors. Two console messages, both expected or already present: the deliberate reused-link 400, and the parent's sign-in probe of `/api/me/` (403).

**Diffs:** grepped for key-like strings and real-looking personal data. Only placeholder phone formats, a UK number from the range reserved for fiction, and made-up `.test` names were found.

## 6. Decisions

**Boarding**
- "Authorised leave" means signed out, or approved leave covering that moment. The sick bay does not excuse a missing mark.
- Archiving a house needs it to have no active boarders.
- All boarding staff can see the unbedded list (as with boarder search).
- The amendment reason is stored on the roll call, not in the activity log.
- Deleting a whole school with boarding history is now refused (Django admin). The demo commands clear that history first.

**Report cards**
- A-4's backfill records a class only where it is certain: no year-end move and no edit to the student since the term began, and the activity log reaches that far. Everything else shows "not recorded".

**Admissions**
- There is no data migration for existing applications: admissions has never been merged, so no real rows exist.
- The duplicate window is 30 days. Declined or withdrawn applications don't count as duplicates.
- Re-enrolment is refused when name and date of birth match an existing student, unless an admin chooses "Enrol anyway". That override is the owner's choice, and it is logged with the existing student's ID.
- Admission numbers are always given on enrolment, as prefix plus next number. Numbers in use are skipped and nobody is renumbered.
- The B-2 and B-5 lock is an UPDATE on the school's admissions row, so SQLite and Postgres both serialise.
- The race tests need concurrent writers, so they skip on SQLite (CI) and were run on Postgres.

**Support and rankings**
- C-1 defaults: 3 marks, 10 days, 10 points.
- D-1 default: 0%, so everyone with a mark is ranked (the owner's choice). A school can set a completeness share.

**Stacking**
- #17 stacks on #14 to share one migration chain; #20 stacks on #17.

## 7. Design notes

- `docs/DESIGN_health_notes_public_form.md` (B-4): recommends a yes/no question, with details collected after an offer.
- `docs/DESIGN_ranking_with_options.md` (D-1): keep the completeness rule; offer "best N" on request.
- `docs/DESIGN_timetable_dates.md` (F): timetable versions from a date, then date overrides.
- `docs/DESIGN_timetable_sets_and_team_teaching.md` (F): extra teachers, then a joint flag, then teaching groups.
- `docs/DESIGN_leave_authority.md` (G): a restriction flag and notifying both parents, then authorised collectors.
- `docs/DESIGN_notifications.md` (G): web push for routine notices, SMS for urgent ones; no prices quoted.

## 8. Additional observations (not fixed: out of scope)

- ~~Bed assignment silently moves out whoever is in the bed.~~ Fixed (X-1).
- ~~The family export misses roll calls, bed, sign-ups, invitations and the change log.~~ Fixed (X-4).
- ~~Open sick-bay visits of a student who leaves are not closed.~~ Fixed (X-2).
- **Parent sign-in noise:** the app asks `/api/me/` first, which logs a 403 in the browser console for every parent sign-in.
- ~~CI runs on SQLite only.~~ The Postgres job was added (X-5, #24).
- **Lint:** `seed_demo_school.py` and `gradebook/systems.py` have unused imports (already there before).
- **The backup workflow** uses actions on Node 20, which GitHub flags as deprecated.
- **Demo data in production:** if `ALLOW_DEMO_SEED=1` was set on Render to seed the demo schools, remove it afterwards.
- **E-2 on SQLite:** loading is slightly slower than before on data with one mark per type (numbers above).
- **C-1 defaults:** a school with fewer than 3 marks per term will see no low-average suggestions until it has them. Shown as "not enough data yet".

## 9. What couldn't be verified

- **CI** on PRs #17 to #23 and frontend #14 to #17: runners were not available (H-13). Every branch passes locally.
- ~~The full backend suite on Postgres.~~ Done locally on the merged tree: 976 tests, OK (section 11).
- **Web push delivery** to a real Google, Apple or Mozilla push service. The encryption is proven by a decrypt round trip in tests; real delivery needs the owner's keys (H-18).
- **Email delivery** with a real provider. The console backend was used, and no provider was contacted.
- **Production data:** the pre-flight and backfill counts on live data, which are owner-only (H-15).
- **Real phones** (H-17).
- **Legal accuracy** of the updated drafts (counsel).

## 10. Owner-only (in `docs/HUMAN_ACTIONS.md`)

- H-13: GitHub Actions runners or billing.
- H-14: the email provider and sender for admissions confirmations.
- H-15: the pre-flight and one-off commands, in order, plus a daily `purge_applications` cron.
- H-16: school-policy decisions (retention, admission number prefix, pass marks, ranking share, health questions, leave authority, SMS provider) and legal sign-off.
- H-17: a real-device check.
- H-18: VAPID keys for phone and browser notifications, and a privacy-notice line.
- H-19: check that `ALLOW_DEMO_SEED` is not set in production.
- H-14 now has the Brevo SMTP steps.

Also owner-only: environment variables and secrets on Render, Vercel and GitHub, backups (H-1), branch protection (H-7), and merging and deploying.

## 11. Owner choices (2026-10-06) and the work they started

**What the owner chose:**
- **Health question:** a yes/no question.
- **Admission numbers:** always assigned.
- **Matching child:** an admin can enrol a different child who shares a name and birthday.
- **Defaults kept:** support 3 marks, confirmation link 48h, applications kept forever.
- **Ranking:** rank everyone.
- **Extra fixes:** all four selected.
- **Leave:** a restriction flag, and both parents are told.
- **Notifications:** push now, SMS later.
- **Email provider:** Brevo.

| ID | What | PR (backend / frontend) | Commits | Tests |
|---|---|---|---|---|
| B-4 (choice) | Public form asks "Does your child have health or learning needs we should discuss?" (Prefer not to say / Yes / No). There is no free text, and old text stays visible to admins until purged | #14 / FE #12 | 092a832, bfe4830 / 062fa19 | admissions.test_fixes.HealthQuestionTests; admissions.test.jsx |
| B-2 (choice) | "Enrol anyway" for a different child with the same name and birthday; logged | #14 / FE #12 | 587efea / 2745893 | DifferentChildTests; admissions.test.jsx |
| D-1 (choice) | Ranking completeness share defaults to 0% | #17 | 7249d36 | test_rank_basis.test_by_default_everyone_with_a_mark_is_ranked |
| X-1 | A bed held by an active boarder needs `replace: true`, and the page asks first. The move-out is logged | #15 / FE #13 | 2ba189a / 9e2ae81 | boarding.test_extras.BedSwapTests; boarding.test.jsx X-1 |
| X-2 | A student who leaves the school is checked out of sick bay ("Left the school") | #15 | 2ba189a | SickBayOnLeavingTests |
| X-3 | Admins mark a boarder "leave only with admin approval" (`/api/boarding/restrictions/`). House staff can't give, approve or sign out that boarder's leave. Every parent is emailed on leave given, approved or signed out, whatever their email setting. The note is staff-only and never logged | #15 / FE #13 | 2ba189a / 9e2ae81 | LeaveRulesTests; boarding.test.jsx X-3 |
| X-4 | The family export adds the current bed, roll-call marks, missing records, invitations, sign-up requests and change-log entries (JSON and xlsx) | #15 | 24185a1 | FamilyExportTests |
| X-5 | CI job `test-postgres` runs the whole suite on Postgres 17 | #24 | fe40add | (workflow) |
| X-6 | Web push for new announcements and ready reports. Parents opt in per device on Profile. The notice has the school name only. Only known push services are accepted (SSRF), and gone devices are forgotten. Off until the VAPID keys are set. New dependencies: `http-ece` and `py-vapid` (pip-audit clean) | #25 / FE #18 | df3a14d, dd12f4f / 59860c9 | communications.test_push (16); push.test.jsx (6) |

**Verification on the merged tree** (all 12 backend and 7 frontend branches, in the order in section 3):
- Backend:
  - 976 tests OK on SQLite (2 skipped: the race tests);
  - 976 OK on a local Postgres 16, where the race tests run;
  - `makemigrations --check` is clean.
- Frontend: 197 tests pass, and the build is clean.
- **Browser smoke** (evidence/owner-choices/):
  - an admin set a leave rule, and it shows with the note;
  - a house staff member sees the rule with no edit controls, and approving that boarder's leave shows "Only an admin can give, approve or sign out leave for Oliver Thomas.";
  - the admin removed the rule;
  - the public form shows the yes/no question and no health text box;
  - no page errors; the only console error is the expected 403.

**Still owner-only:**
- Brevo SMTP settings (H-14);
- VAPID keys (H-18);
- checking `ALLOW_DEMO_SEED` (H-19);
- re-running CI once runners work (H-13), then making `test-postgres` required;
- choosing an SMS provider when wanted.
