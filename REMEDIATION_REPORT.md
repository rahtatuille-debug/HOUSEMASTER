# HouseMaster: remediation of the production readiness audit

**Date:** 2026-09-28
**Covers:** findings F-01 to F-20 and extra items E-1 to E-7 from the Production Readiness Report of 2026-09-28.
**Branches:**
- Backend (`rahtatuille-debug/housemaster`), stacked in this order:
  - `claude/remediation-phase-1`
  - `claude/remediation-phase-2`
  - `claude/remediation-phase-3`
- Frontend (`rahtatuille-debug/housemaster-frontend`):
  - `claude/remediation-phase-1`, the compatibility release, which ships first
  - `claude/remediation-phase-2`

Nothing was pushed to `master` or `main`, nothing was merged, and nothing touched Render, Vercel or Neon. All testing used scratch SQLite databases and a local PostgreSQL 16, with `DATABASE_URL` unset.

---

## 1. Summary

**Status:** every finding has code, tests or documentation. The contracts, dashboard settings and repository settings that only the owner can change are prepared as step-by-step instructions (§4). Once the owner has done H-1 to H-8, Tier 1 (a closed pilot) is achievable.

**What changed:**
- **Parent messaging (F-01).** Parents can no longer list other families or message other parents. Every refused person or child gets the same answer as one that doesn't exist.
- **Configuration (F-03).** Production refuses to start with a missing or unsafe setting. The old dev key, which was public, is gone.
- **Sessions (F-04).** A password change or reset ends every session. Refresh tokens rotate, and there's a real logout.
- **Rate limits (F-05).** Login, password reset, invites, sign-up and registration are limited per IP and per email, and spoofed IP headers stop working once the proxy count is set.
- **AI calls (F-07, F-08).** A slow provider can't freeze the app, provider errors become a clean 503, and no child's name goes to the AI.
- **Data integrity (F-09 to F-14).** Formula injection, impossible grades and attendance dates, blank report comments, duplicate emails and unbounded lists are all fixed, with database-level backstops and PII-free pre-flight checks.
- **CI and tests (F-06, E-5).** CI now runs on both repositories: 160 new backend tests and the frontend's first 22.

**What's left is human-only:**
- Switch on the backups and run a restore drill (the scripts passed a full local drill).
- Set the Render and Vercel environment.
- Protect the default branches.
- Move Gemini to a no-training paid tier and sign the data-processing agreements.
- Upgrade hosting before a second school.

---

## 2. Finding by finding

Status key: **Done** means code plus tests (or the complete deliverable). **Blocked-on-human** means the code side is done and one step needs the owner.

| ID | Status | Commits (backend `be`, frontend `fe`) | Tests added | Notes and deviations from the prompt |
|---|---|---|---|---|
| F-01 | Done | be 5028a97 | `messaging/test_contact_rules.py` (16) | One rule module, `messaging/contacts.py`. Old staff-only error messages were existence signals; now every refusal gives the same "not found" answer. Staff-to-staff direct messages are still allowed, as before. |
| F-02 | Blocked-on-human (H-1, H-2) | be 7727829 | Local drill (§3) | `scripts/create_backup_role.sql`, an optional S3 copy step, and `docs/BACKUPS.md` rewritten. The fail-loudly secrets check is unchanged. A full drill ran against local Postgres 16. |
| F-03 | Done (deploy needs H-3 first) | be 19b38d5 | `housemaster/test_settings_guard.py` (19 in total, 13 for F-03) | `DEBUG` defaults to False. Raises on a missing or unsafe `SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS` or `CORS_ALLOWED_ORIGINS`. Deploy checks E001 (`FRONTEND_URL`) and E002 (email). Tests use `DJANGO_DEBUG=True` (README one-liner). |
| F-04 | Done | be 02998b5; fe 00e9116 | `accounts/test_token_revocation.py` (14); `src/api.test.js` (7) | `accounts.UserSecurity.token_version`, bumped by a `post_save` hook on any password-hash change or deactivation (covers reset, admin and `set_password`). A missing claim counts as version 0. Rotation and blacklist are on; `POST /api/logout/`; refresh tokens last 3 days. The frontend uses single-flight refresh, a Web Lock across tabs, and best-effort logout. Role and assignment changes were never cached in tokens, so they don't bump the version. |
| F-05 | Done (H-5 and `DRF_NUM_PROXIES` to finish) | be 60ba0cf | `accounts/test_throttling.py` (16), plus W001 and debug-middleware tests | Per-IP and per-email limits. **Deviation:** login counts failed attempts only, so shared school and mobile addresses don't lock out colleagues. **Deviation:** refresh is 600/h, not 120/h, because of carrier-grade NAT. `DRF_NUM_PROXIES` is not guessed; `LOG_CLIENT_IP_DEBUG` is there to measure it. `THROTTLE_CACHE=db` is an option. Minimum password length is now 10. |
| F-06 | Blocked-on-human (H-7) | be 372392d, 37e24e2; fe 4c289f2 | CI workflows | Backend: check, `check --deploy --fail-level ERROR`, `makemigrations --check`, `pip-audit`, tests. Frontend: `npm ci`, tests, build, `npm audit --omit=dev`. The branch-protection commands are written (H-7) but not run. A deliberately broken branch is covered in §3. **Found by CI itself:** the first runs failed because `students/test_preview.py` needs `pypdf`, which was never in `requirements.txt` (it only existed in development environments). CI now installs `requirements-dev.txt` (`-r requirements.txt` plus pinned `pypdf`, `tblib` and `pip-audit`); production still installs only `requirements.txt`. |
| F-07 | Done | be 236fe74 | `reporting/test_ai_failures.py` (11) | `reporting/ai.py`: `HttpOptions(timeout=20000)` (google-genai 0.8.0 takes milliseconds) plus a thread-pool hard deadline 5 s later. Provider and network errors return 503, and nothing is saved. `GEMINI_MODEL` setting. `gunicorn.conf.py`: gthread, 1 worker, 4 threads, 60 s timeout. |
| F-08 | Done (contract: H-8) | be 811afd2 | `reporting/test_ai_privacy.py` (5) | `[STUDENT]` placeholder, with the first name put back locally. Announcement briefs have known full names and email addresses masked and restored, and the school's name is dropped. `docs/AI_DATA_FLOW.md`. Coverage of `reporting/services.py` is 97% (was 49%). |
| F-09 | Done | be 04240a7 | `reporting/test_formula_injection.py` (5) | `reporting/spreadsheets.append_row` for every workbook, including both import templates and the family export. The app writes no CSV files. |
| F-10 | Done (pre-check: H-6) | be 87795e4 | `gradebook/test_ranges.py` (11) | Serializer checks the pair as it will be saved; DB `CheckConstraint`s behind a PII-free pre-flight; `scripts/preflight_range_checks.sql`. Attendance allows up to 1 day ahead, and more than 5 years back only if a term covers the date. Grades and attendance don't go through the approvals workflow, so there is no approvals path to test. |
| F-11 | Done | be 8d0e0af | `reporting/test_blank_reports.py` (9) | An unusable AI answer returns 502 and nothing is saved. `StudentReport.missing_content()` and the queryset `blank()` / `with_content()` block submit and finalize; class-wide actions skip blank reports and report how many; parents never see a blank report. |
| F-12 | Done | be ce3ff67 | `accounts/test_invite_privacy.py` (8) | **The prompt's premise didn't hold:** invite creation already checked only the admin's own school. That is now covered by tests. Added invite-email limits of 100/h per admin and 5/day per recipient. Residual risk is documented in `docs/SECURITY_NOTES.md`. |
| F-13 | Done (pre-check: H-6) | be 0dece57, 2911127 | `accounts/test_unique_email.py` (6) | `RunSQL` unique index on `LOWER(email)` where email isn't empty, with a reverse. Pre-flight names user IDs only. `create_account()` turns a race into a friendly 400 for registration and both invite accepts. |
| F-14 | Done | be df5f517; fe 886ad0c, a3c0696, ee6433d | `gradebook/test_pagination.py` (8); `src/api.test.js` (5); `src/panels/Grades.test.jsx` (2) | Grades, attendance and messages are paged: 100 rows by default, up to 500 via `?page_size`. The activity log was already paged at 50. The Grades screen pages on the server; the register and a student's history need every row, so they fetch the whole filtered list. |
| F-15 | Done (enforce: H-12) | fe 9b1bdfb; be af108ea, be7ea2f | Browser check (§3) | Report-only CSP and security headers in `vercel.json`, derived from the build. Zero violations in a full click-through. The httpOnly cookie design is in `docs/DESIGN_httpOnly_refresh.md`; nothing is built. |
| F-16 | Done | be 3b74ba5 | `students/test_data_subject.py` (8) | **The audit was wrong** that no tooling existed: `students/privacy.py` already had an export and removal. Added subject comments and conversations about the child to the export (plus JSON), scrubbing on removal, deletion of sign-up requests, and `apply_retention` (off, dry-run by default). No frontend change is needed (the Data protection panel exists). Design is in `docs/DESIGN_data_subject_tooling.md`. |
| F-17 | Done | be d4d5711 | `accounts/test_admin_hardening.py` (9) | `DJANGO_ADMIN_PATH` (default `admin/`; production should change it), a throttle on failed admin logins, and `sync_superuser` that only creates the user (`SYNC_SUPERUSER_RESET_PASSWORD=true` resets it for one deploy). Admin changes are recorded in Django's `LogEntry`, not the app's activity log. |
| F-18 | Done | be 79c9b06 | `accounts/test_email_failures.py` (5) | In production, the console backend is replaced by `UndeliveredEmailBackend` (an ERROR log, never the link). Reset send failures are logged and the public answer stays uniform; admins are told (503). |
| F-19 | Done | be 28780c3 | `housemaster/test_hardening.py` (6) | HSTS 30 days (`SECURE_HSTS_SECONDS`, no preload). `TIME_ZONE=Africa/Nairobi`, and every `date.today()` became `localdate()`, in tests too. Subject reports for a class the teacher doesn't teach now return 403. |
| F-20 | Blocked-on-human (H-10) | be f624966 | none (docs only) | README Deployment section. |
| E-1 | Done | be 372392d | Clean-venv install and full suite (§3) | `.python-version` 3.13; `requirements.in` compiled to a pinned `requirements.txt`. Folded into the F-06 commit because CI needs it. |
| E-2 | Done | be 0567cc2, f2d22ed, db4d2bf | none (docs only) | `ENVIRONMENT`, `HUMAN_ACTIONS`, `ROLLOUT`, `RUNBOOK`, `PILOT_CHECKLIST`, `BACKUPS`, `SECURITY_NOTES`. |
| E-3 | Done (needs H-11 first) | fe 4a91e39 | `src/buildGuard.test.js` (3) | Fails when `VERCEL_ENV=production` and `VITE_API_BASE_URL` is unset; warns without a Sentry DSN. Checked with real builds. |
| E-4 | Done | be 4676825 | `housemaster/test_remote_db_guard.py` (4) | `manage.py test` refuses a non-local database unless `ALLOW_REMOTE_TEST_DB=1`, and never echoes the URL. Needed because `.env` was loaded even with `env -u DATABASE_URL`. |
| E-5 | Done | fe 616e0c5 | 22 frontend tests in total | Vitest and React Testing Library: identity fork, rotation and single-flight refresh, message ownership, both list shapes, crash boundary, build guard, Grades paging. |
| E-6 | Done | none | none | New overall coverage figure in §3. |
| E-7 | Done | none | none | Full suite run with `--shuffle 20260928` (§3). |

---

## 3. Before and after

Re-running the audit's own harness (`test_zz_audit*.py`) against the Phase 3 code needed small shape adjustments: paged lists, re-signing in after its own password changes, and 70 invite guesses instead of 50. Every check expectation stayed as the audit wrote it.

| Probe | Before (audit) | After |
|---|---|---|
| Cross-tenant detail matrix (11 object types, GET/PATCH/DELETE) | 64 OK / 0 FAIL | 64 OK / 0 FAIL (isolation intact) |
| Parent DMs another parent | 201 | 400 "One or more participants could not be found." |
| Parent attaches another family's child | 201, `student_name: "Akid2 Y"` | 400, no name (`{"participant_ids": [...not be found], "student": ["Student not found."]}`) |
| Parent walks user IDs 1–39 | 5 conversations created, revealing other parents' names | Only the 2 allowed (their child's teacher and the admin); everything else gives the identical "not found" |
| Parent contacts list | Whole staff directory (3) | Own child's teacher and admins (2) |
| Token forged with the public dev key | Accepted by auth (403 only for lack of a school) | App refuses to boot: `ImproperlyConfigured: SECRET_KEY is not set` |
| Old access and refresh tokens after a password change | 200 / 200 | 401 / 401 |
| Old access and refresh tokens after a password reset | 200 / 200 | 401 / 401 |
| Rotated refresh token replayed | Reusable | 401 (unit test); live browser run: rotated, still signed in, one refresh call |
| 60 wrong logins | all 401 | 401 then 429 |
| 40 reset requests for one email | 40 emails sent | 5 sent, then 429 |
| 50 (now 70) invite-token guesses | No 429 | 429 after 60 in an hour |
| 12 registrations with rotating spoofed `X-Forwarded-For` | 12 × 201 | With `DRF_NUM_PROXIES=1`: 5 × 201 then 7 × 429. Unset (as in the tests), still 12 × 201: **H-3 must set it** |
| Gemini stall, one worker | Other user's `/api/me/` took 30.08 s; generate returned 500 at 30.37 s | `/api/me/` 5–8 ms; generate returns 503 "busy" at 25.0 s |
| Gemini `ConnectionError` / SDK 429 | 500 | 503 "The writing assistant is busy…" |
| `=HYPERLINK(...)` in class export | Formula cell (`f`) | Text cell (`s`) |
| Grade 150/100, −5, max 0; attendance +400 days | All 201 | All 400 |
| Malformed AI output, then finalize | Saved empty; submit 200, finalize 200 | 502 and nothing saved; blank report: submit 400, finalize 400 |
| Teacher asks for another class's subject entries | 200 with empty data | 403 "You don't teach this class." |
| Duplicate-email race | Duplicate account possible (201), or 500 | One account plus a friendly 400; DB index blocks case variants |
| `/api/grades/` with 1,200 students / 6,000 grades | 6,005 rows, 906 KB, 302 ms, 4 queries | 100 rows a page, 15 KB, 14 ms, 6 queries on page 1 and on page 30 |
| Production settings with each critical variable missing | Booted with fallbacks | Refuses to start (11 subprocess tests); `check --deploy` gives E001/E002/W001 for `FRONTEND_URL`, email and proxy count |

**Test suites**

| Run | Result | Duration |
|---|---|---|
| Phase 1 backend, full, serial | **546 tests, OK** | 1,615 s |
| Phase 2 backend, full, serial | **604 tests, OK** | 1,961 s |
| Phase 3 backend, full, serial, `--shuffle 20260928` (E-7, different order) | **621 tests, OK** | 2,016 s |
| Phase 3 backend (merged head `77201ab`), full, clean venv from `requirements-dev.txt` (the pinned requirements plus test tools), with coverage (E-1, E-6) | **621 tests, OK** | 2,002 s |
| GitHub Actions, every PR branch (parallel runner) | Green (see CI below) | about 4 min |
| Frontend phase-1 / phase-2 from clean checkouts | 20 / 22 tests passed; `npm ci`, build and `npm audit --omit=dev` all clean | — |

**Other checks**
- **Coverage:** before, 92% (line and branch). After: **93%** (6,569 statements, 1,462 branches). `reporting/services.py` went from 49% to 97%.
- **Migrations:**
  - `makemigrations --check`: no changes.
  - Migrate on an empty SQLite database (every test run) and on PostgreSQL 16:
    - The seeded demo copy (601 students, 18,526 grades) took 1.4 s.
    - A fresh copy with 1,200 students, 6,000 grades and injected bad rows: the pre-flight stopped with "user IDs 1, 2" (no address), then "grade IDs 6001, 6002". Both applied after the rows were fixed. The reverse migrations work.
- **`check --deploy --fail-level ERROR`** with a production-like environment: only `security.W021` (no HSTS preload, deliberate).
- **Dependencies:** `pip-audit -r requirements.txt` and `npm audit --omit=dev` both report no known vulnerabilities. A clean virtualenv from `requirements.txt` passes `pip check`.
- **Browser smoke tests** (Playwright, Chromium, local servers, demo data):
  - The **compat frontend against today's backend**: admin 17 tabs, teacher 14, parent 4, with no page errors. `/api/logout/` returns 404 there, which is ignored.
  - The **new frontend against the Phase 3 backend** with the report-only CSP served: same tabs, **zero CSP violations**, logout 200, refresh rotation working live.
- **Backup drill** (local Postgres 16):
  - `create_backup_role.sql` created the read-only role.
  - Encrypted backup of 43 tables and 41,107 rows took 4 s.
  - A DELETE as the backup role was refused ("read-only transaction").
  - Restore into an empty database matched every row count in 3 s.
- **Secrets:** a grep of every diff for key-like strings found only placeholders, test values and command templates. No `.env` file is tracked.
- **CI:**
  - The latest runs on every PR branch are green: backend phase-1 [36421828509](https://github.com/rahtatuille-debug/HOUSEMASTER/actions/runs/36421828509), phase-2 [36421830655](https://github.com/rahtatuille-debug/HOUSEMASTER/actions/runs/36421830655), phase-3 [36421834105](https://github.com/rahtatuille-debug/HOUSEMASTER/actions/runs/36421834105); frontend phase-1 and phase-2 (runs 36420506967 and 36420508584).
  - **Deliberately broken branch:** `claude/ci-demo-broken-test` added one failing test (`assertEqual(1 + 1, 3)`) on top of phase-3. Run [36421837784](https://github.com/rahtatuille-debug/HOUSEMASTER/actions/runs/36421837784) went **red**. Log excerpt:
    ```
    File ".../housemaster/test_ci_demo_broken.py", line 7, in test_ci_catches_a_failure
      self.assertEqual(1 + 1, 3)
    AssertionError: 2 != 3
    Ran 547 tests in 237.709s
    FAILED (failures=1)
    ##[error]Process completed with exit code 1.
    ```
  - The local copy of the demo branch is deleted. **The remote branch could not be deleted from this sandbox:** the git proxy refuses branch deletions ("remote end hung up", four attempts), and the GitHub tools available here cannot delete refs. The owner should delete `claude/ci-demo-broken-test` on GitHub (Branches page, bin icon); it is not part of any PR.

---

## 4. Owner's checklist (`docs/HUMAN_ACTIONS.md`), in order

Exact commands, and how to check each one worked, are in `docs/HUMAN_ACTIONS.md`. In short:

1. **H-2**: create the read-only Neon role (`scripts/create_backup_role.sql`). **H-1**: set `BACKUP_DATABASE_URL` and `BACKUP_PASSPHRASE`, and optionally the S3 secrets; run the backup workflow; do the restore drill and fill in the RPO/RTO table. *Check:* "OK: … restored and match".
2. **H-3**: set the Render environment before the Phase 1 backend deploy: `DJANGO_DEBUG=False`, a **new** `SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`, SMTP settings, `DEFAULT_FROM_EMAIL`, `SENTRY_DSN`; then measure and set `DRF_NUM_PROXIES`. Warn staff that they will be signed out once. *Check:* `check --deploy --fail-level ERROR` passes locally with the same values; sign in on the live site.
3. **H-4**: the Render start command must be exactly `gunicorn housemaster.wsgi`; set `WEB_CONCURRENCY=1`. *Check:* the log shows `Using worker: gthread`.
4. **H-11**: set `VITE_API_BASE_URL` and the Sentry variables on Vercel Production (and Preview). *Check:* redeploying current production succeeds.
5. **H-5**: add `createcachetable`, `flushexpiredtokens` and `check --deploy --fail-level ERROR` to the Render build; set `THROTTLE_CACHE=db`. *Check:* 10 wrong passwords, then 429.
6. **H-7**: protect `master` and `main` with the `gh api` commands given (required checks `test` and `build`). *Check:* a direct push is refused.
7. **H-6**: before the Phase 2 backend deploy, run `scripts/preflight_range_checks.sql` and `scripts/preflight_duplicate_emails.sql` with the read-only login. *Check:* every count is 0.
8. **H-8**: move to a paid Gemini tier with no training on prompts, and accept Google's DPA; sign a DPA with the pilot school; publish the privacy notice.
9. **H-9**: decide whether the repositories should be private (mind the Vercel Hobby limits). Rotate `SECRET_KEY` either way (done in H-3).
10. **H-10**: before a second school, upgrade to Render Starter (then `WEB_CONCURRENCY=2`) and Neon Launch, and add uptime monitoring and Sentry alerts to a phone.
11. **H-12**: after several clean days, rename the frontend's CSP header to enforcing.

---

## 5. Rollout plan (`docs/ROLLOUT.md`)

| Step | Merge or do | Watch | Rollback |
|---|---|---|---|
| 0 | H-3, H-4, H-11 (environment only) | Nothing deploys | none |
| 1 | Frontend `claude/remediation-phase-1` → `main` | Sign in and out, each role; leave a tab open for over an hour; Sentry | Revert the merge (no data involved) |
| 2 | Backend `claude/remediation-phase-1` → `master` (**only after step 1 is live**) | Log shows `gthread` and no `ImproperlyConfigured`; the parent's contact list; one AI comment; Sentry | Revert the merge. The new tables (`accounts_usersecurity`, `token_blacklist_*`) can stay. A failed build keeps the old version live. |
| 3 | H-1, H-2, H-5, H-7 | Backup green; throttle works | none |
| 4 | H-6 pre-checks | All zeros | none |
| 5 | Backend `claude/remediation-phase-2` | Marks, attendance, activity, a long conversation, an export | Revert the merge. The constraints and index are additive, and each migration has a reverse. A stopped migration on Postgres can leave only the email index applied, which is harmless. |
| 6 | Frontend `claude/remediation-phase-2` | Every page; console clear | Revert the merge |
| 7 | Backend `claude/remediation-phase-3` (set `DJANGO_ADMIN_PATH` first) | Admin at the new path; an export | Revert the merge (no migrations) |
| 8 | H-12: CSP to enforcing | Every page still works | Rename the header back |

Branches are stacked. Each pull request targets `master` or `main`; merge them in order, and each diff narrows to its own changes once the one before it is merged.

---

## 6. Risks and decisions I made where the prompt left room

- **Failed-only login throttle.** Counting every login would lock out a school's staff sharing one address each morning. The trade-off: an attacker can lock one email out for an hour with 10 wrong passwords. That is accepted, and documented.
- **Refresh limit of 600/h, not 120/h.** Many parents reach the site through one carrier-grade NAT address.
- **`DRF_NUM_PROXIES` isn't defaulted to 1.** A wrong value either keeps the header bypass open or puts everyone in one bucket. The debug switch measures it instead.
- **No-claim tokens count as version 0.** The deploy signs nobody out. A new `SECRET_KEY` still signs everyone out once, which is intended.
- **Hash upgrades end sessions.** Any password-hash change, including Django re-hashing on login after a Django upgrade, ends that account's other sessions. That is acceptable and rare.
- **Hard deadline on AI calls.** A thread pool abandons a stuck call after 25 s. An abandoned thread finishes in the background, and the pool of 4 bounds that.
- **Announcement masking.** It only recognises full names of known pupils and parents, and email addresses. A bare first name typed into a brief still goes to Gemini; staff guidance is in `AI_DATA_FLOW.md`.
- **Parse failure means 502 and nothing saved.** An unusable AI answer is refused rather than saved as a "needs manual comment" draft, so a teacher's existing draft is never overwritten.
- **Attendance date bounds.** Up to 1 day ahead of the school's date (registers prepared the night before), and more than 5 years back only if a term covers the date (old imports).
- **Paging scope.** Only grades, attendance and messages. Conversations, announcements, reports and change requests grow more slowly and stay whole (see §7).
- **Family export stays Excel, plus JSON.** Families can open the workbook; JSON is for checks. Activity-log summaries stay readable sentences rather than a 96-call-site rewrite; removal scrubs names.
- **Admin path default stays `admin/`.** Changing it would break the owner's bookmark silently; production is told to set `DJANGO_ADMIN_PATH`.
- **`TIME_ZONE` is fixed to Nairobi.** That is right for the Kenyan pilot; see §7 for schools elsewhere.
- **Vitest stays at 2.x.** Vitest 5 needs a Vite major upgrade. The advisories are dev-only.
- **Branch names.** The session's own branch was `claude/upbeat-wright-jnkpdv`; I used the `claude/remediation-phase-*` names the task asked for.
- **Bundled commits.** E-1 is folded into the F-06 commit, because CI needs the pinned toolchain. F-13 and F-14 each have a follow-up commit (test fixtures, and the activity-log paging fix) rather than rewritten history.

---

## 7. Additional observations (found, deliberately not fixed)

1. **Self-service password reset is broken in production today.** The "Forgot password" screen posts `{username}`, but `/api/password-reset/` requires `email`, so every request is refused with a 400 ("email: This field is required") (`src/api.js`, `requestPasswordReset`). Admin-sent resets work. It's a one-line fix, but outside the findings.
2. **Time zone for non-Kenyan schools.** "Today" is now Nairobi's day for every school. The product has UK, US and IB presets, and schools there need a per-school time zone.
3. **The audit got two things wrong.** Data-subject tooling already existed (F-16), and the F-12 invite-creation oracle didn't. The remediation built on what was there.
4. **Staff can mix families.** A teacher can open one direct conversation with parents of different families, and those parents then see each other's names. Class discussions show parents to each other by design. This belongs with counsel question 7.
5. **The bulk staff import bypasses the invite limits.** It creates invites and emails outside the new per-admin and per-recipient limits (admin-only).
6. **Other growing lists.** Conversations, announcements, reports and change requests are still unpaginated.
7. **Shared token-guessing bucket.** Password-reset confirmation shares the per-IP bucket with invite and sign-up-link endpoints (60/h), so a burst of parents joining from one address could briefly delay a reset from that address.
8. **Dev-only npm advisories.** Vitest 2 (its UI server, not used), esbuild through Vite 5 (dev server) and nanoid; they need a Vite major upgrade.
9. **Minor leftovers.** `students/profile.py` has two pre-existing unused imports, and the README's "Next steps" section is out of date.
10. **Demo password in production.** `seed_demo_school` would create demo schools with a shared password if `DEMO_PASSWORD` were ever set in production (documented as must-stay-unset).

---

## 8. What I could not verify

- **Render, Neon and Vercel.** I couldn't check their dashboards, the real hop count behind `X-Forwarded-For`, the start or build commands, or whether production currently uses the old key. The sandbox has no access, and the task forbids touching production.
- **A GitHub-hosted backup run.** It needs the secrets (H-1). The scripts were proven locally, with `pg_dump` 16 rather than the workflow's 17.
- **The live Gemini API.** The paid tier, the DPA and the exact 429/5xx shapes of the live service are unverified. The installed SDK's error classes were used in the tests.
- **Real email delivery** (SMTP, SPF, DKIM, DMARC).
- **Real devices and Google Fonts.** Browser checks ran in headless Chromium, and Google Fonts couldn't load through the sandbox proxy. So the `font-src` rule is correct by construction but hasn't been observed loading a font. Safari's behaviour with Web Locks and the CSP is untested.
- **Branch protection (H-7)** was not applied, by instruction.
