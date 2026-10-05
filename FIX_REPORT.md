# FIX_REPORT: the ⚠ items from the known-gaps list

(Plan first; the full report replaces this file at the end. Identical on every branch, so merging the PRs in any order never conflicts on it.)

## Step 0: where things really are

Checked with `git fetch --all` and the GitHub API on 2026-10-05.

| Module | State |
|---|---|
| Rankings, "most improved", positions in the Excel export | merged (backend #10, frontend #8) |
| Needs support (suggestions, plans, parent card) | merged (backend #10, frontend #8) |
| Report cards keep their class; faster analytics; year-group order | merged (backend #11, frontend #9) |
| Timetable | merged (backend #12, frontend #10) |
| Boarding (houses, beds, roll calls, leave, sick bay) and its on/off switch | merged (backend #13, frontend #11) |
| Offline drafts, installable app | merged (frontend #7) |
| **Admissions** | **open: backend #14, frontend #12; CI green on both; base `master` / `main`** |

Baseline on a clean `origin/master` and `origin/main`: frontend 150 tests pass and the build is clean; backend isolation, approvals, guardians and messaging suites: see the results section.

## Stack plan: which branch each fix goes on

Everything is based on `master` / `main` except the admissions fixes, which are added as commits to the open PR branches `claude/upbeat-wright-jnkpdv` (backend #14, frontend #12). Nothing is merged and nothing is force-pushed.

| Branch (backend and frontend, same name) | Items | Why this branch |
|---|---|---|
| `claude/fix-a-boarding-safeguarding` | A-1, A-2, A-3, A-5, A-6 | boarding code is merged; one PR so the migrations are numbered in order |
| `claude/fix-a4-report-class` | A-4 | reporting code, separate risk, separate PR |
| `claude/upbeat-wright-jnkpdv` (open PRs #14, #12) | B-1 to B-5, and the admissions part of H | the code only exists in that branch |
| `claude/fix-cd-support-ranking` | C-1, D-1 | both add school settings, so one migration chain |
| `claude/fix-c2-legal-docs` | C-2 | documents only |
| `claude/fix-e1-students-paging` | E-1 | needs the frontend and backend together |
| `claude/fix-e2-analytics` | E-2 | |
| `claude/fix-f-timetable` | F, and the two timetable design notes | |
| `claude/fix-g-checks` | G (register test, demo guard test, design notes) | |
| `claude/fix-h-isolation` | H (tests for the merged modules; BLOCKER fixes get their own commits) | |

Merge order is in the final report.
