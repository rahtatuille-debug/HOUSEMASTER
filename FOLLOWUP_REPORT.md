# HouseMaster follow-up report

*Follow-up to the production-readiness remediation (REMEDIATION_REPORT.md).
This file is identical on every follow-up branch in both repositories.*

## 1. Summary

Everything in the follow-up list that is code, tests, scripts or documents
is done, on seven branches stacked on the unmerged remediation branches
(backend `claude/remediation-phase-3`, frontend `claude/remediation-phase-2`).

- **Frontend "Forgot password" fixed:** it asks for the email address.
- **Reset and import limits:** password-reset confirmation now has its own
  limit, and the bulk staff import respects the invite limits.
- **Parents:** two parents of unrelated families can no longer be put in
  one conversation.
- **Health check:** added `/healthz`.
- **Demo data:** the demo seeder refuses to run on a production server.
- **Long lists** are paged.
- **Time zones:** each school has its own.
- **Urgent alerts:**
  - always emailed;
  - limited per school;
  - can be sent as a staff-only test.
- **Fonts** are self-hosted.
- **Token refresh** is single-flight in every browser.
- **Toolchain:** Vite, Vitest and jsdom are current, with 0 audit findings.
- **Owner tools:** a post-deploy smoke check, an email-DNS check, a browser
  smoke suite and a printable merge-day checklist.
- **Legal drafts:** marked as drafts, not legal advice.

Nothing was merged or deployed, and production was never touched.

## 2. Items

Test counts are the tests added for the item (backend: test methods;
frontend: `it` blocks). Every item's tests failed before its fix and pass
after it.

| ID | Status | Commits | Tests | Notes |
|---|---|---|---|---|
| F-1 | Done | be `df76160`; fe `a0f7205` | be 3 (`accounts/test_reset_contract.py`); fe 4 (`ForgotPassword.test.jsx`) | Field is "Email address", type email. 429 shows "try again in …". Checked in a browser end to end. |
| F-2 | Done | fe `b1cf2c6`; be `3b80192` (note) | fe 4 (`fonts.test.js`) | `@fontsource` variable fonts (Latin). Preloaded. CSP `font-src 'self'`, `style-src 'self' 'unsafe-inline'`. No foreign hosts on any screen. |
| F-3 | Done | fe `25baf59` | fe 8 (`refreshLock.test.js`) | In-tab single-flight plus a 10 s localStorage lease when Web Locks are missing or throw. Checked with two real tabs. |
| F-4 | Done | fe `37d05cf` | fe 12 (`usePagedList.test.jsx` 5, `pagedPanels.test.jsx` 7) | Reports, announcements and change requests use "Show more". The badge asks for `page_size=1`. |
| F-5 | Done | fe `98803ec` | fe 6 (`TimeZoneCard.test.jsx`) | Setup → School time zone, shown to admins only. |
| F-6 | Done | fe `f89aa0a` | existing 63 pass | Vite 5→8, plugin-react 4→6, Vitest 2→5, jsdom 25→30, `engines.node >=22.12`. `npm audit` (all deps): 0. JS gzip 131.5→127.6 kB. |
| F-7 | Done (optional) | fe `2a25b26`; be `3bd6f5e` | 6 Playwright tests (`e2e/`) | Not in CI. Read-only against non-local hosts unless `--allow-mutations` is given. |
| B-1 | Done | be `5d01221` | be 19 (`housemaster/test_list_pagination.py`) | See the notes below the table. |
| B-2 | Done | be `8e9ad30`; fe `e1e3011` | be 8 (`accounts/test_import_limits.py`); fe 2 (`StaffImportCard.test.jsx`) | Rows over the limit are "deferred", not created and not emailed. Deferred rows are listed by number. |
| B-3 | Done | be `1757ba7` | be 4 (`accounts/test_reset_confirm_throttle.py`) | `password_reset_confirm_ip`, 60/hour, separate from the request limit. |
| B-4 | Done | be `bd362a1` | be 15 (`students/test_school_timezone.py`) | See the notes below the table. |
| B-5 | Done | be `ae71ad9` | be 10 (`messaging/test_family_mixing.py`) | See the notes below the table. |
| B-6 | Done | be `ec26c44` | be 12 (`housemaster/test_healthz.py`) | See the notes below the table. |
| B-7 | Done | be `028644e` | be 7 (`students/test_demo_seed_guard.py`) | Refuses when `DEBUG` is off unless `ALLOW_DEMO_SEED=1`. |
| B-8 | Done | be `7990c1d` | lint only | Unused imports removed. README "Next steps" rewritten. CI runs `ruff check --select F` (non-blocking). |
| B-9 | Done | be `361347b`, `ff50bce`, `fe49fd6`; fe `3582d03` | be 13 (`communications/test_alert_safeguards.py`); fe 5 (`Alerts.test.jsx`) | See the notes below the table. |
| B-10 | Done | be `22419bd`, `20b6c6d` | — | `docs/MERGE_DAY_CHECKLIST.md`; ROLLOUT steps 9–15. |
| B-11 | Done | be `66a2d8b` | be 6 (`housemaster/test_smoke_check.py`) | `scripts/smoke_check.py`, stdlib only, read-only. Exits 1 on any failure. |
| B-12 | Done | be `cad0df5` | be 11 (`housemaster/test_check_email_dns.py`) | `scripts/check_email_dns.py`: SPF, DKIM, DMARC. |
| B-13 | Done (drafts) | be `e6568af` | — | `docs/legal/`: 11 files. See the notes below the table. |
| E-5 | Done | fe `df54def` | existing test fixed | Flaky `App.test.jsx` "identity fork": 20/20 stable. |
| Stray branch | Not done | — | — | Deleting `claude/ci-demo-broken-test` was refused by the git proxy (tried once, as instructed). It is on the owner list (D10). |

Notes on the longer items:

- **B-1.**
  - Conversations are always paged: `{count, next, previous, results}`, with annotations instead of per-row queries.
  - Reports, announcements and change requests are paged only when `page` or `page_size` is sent. Without them the list shape is unchanged.
  - The remediation frontend already reads both shapes.
- **B-4.**
  - `School.timezone`, default `Africa/Nairobi`; migration `students/0012`.
  - Admins set it; teachers get 403.
  - "Today" is school-local in attendance, the dashboard, teacher home, ages, promotion and report dates.
- **B-5.**
  - A direct conversation between parents needs a shared child.
  - It is refused with the same error as an unknown user.
  - This is a counsel question in SECURITY_NOTES.
- **B-6.**
  - `GET`/`HEAD /healthz`, first in the middleware.
  - Database `SELECT 1`, with a 2 s timeout on Postgres.
  - Returns a 503 on failure, and a short commit hash.
- **B-9.**
  - Inventory in `docs/COMMUNICATIONS_STATUS.md`.
  - Every alert is emailed, in the background after commit.
  - Limits: 10 alerts per school per day; 5 test alerts per day; 30 class messages per hour.
  - Test alerts are admin-only and go to staff only. They are marked TEST in the banner and the subject.
- **B-13.**
  - Every file carries the banner, [VERIFY] markers, and no section numbers or fine amounts.
  - 14 questions for counsel.

## 3. What changed for the owner

- **New Render setting after backend follow-up 1:** Health Check Path `/healthz`
  (merge-day checklist B8).
- **New optional environment variables**, all with safe defaults:
  - `PASSWORD_RESET_CONFIRM_IP_RATE` (60/hour)
  - `ALERT_SCHOOL_RATE` (10/day)
  - `ALERT_TEST_SCHOOL_RATE` (5/day)
  - `CLASS_MESSAGE_RATE` (30/hour)
  - `ALLOW_DEMO_SEED` (leave unset in production)

  All are listed in `docs/ENVIRONMENT.md`.
- **Two migrations** (`students/0012`, `communications/0004`). Each only adds
  a column with a default. They were tried on a copy of the seeded
  1,200-student database and reverse cleanly. No pre-flight query is needed.
- **Urgent alerts are now always emailed.** A school is limited to 10 a day.
  Admins can send a **test alert** to staff.
- **Parents** can no longer start a conversation with a parent of another
  family.
- **Staff import:** rows beyond the invite limits are now reported as
  "deferred"; import them again later.
- **New tools you run yourself:**
  - `scripts/smoke_check.py` (after each deploy)
  - `scripts/check_email_dns.py` (before real email)
  - the frontend's `e2e/` browser suite (optional)
- **Documents to read:**
  - `docs/MERGE_DAY_CHECKLIST.md` (start here)
  - `docs/COMMUNICATIONS_STATUS.md`
  - `docs/legal/`, which counsel reads before any real children's data
- **Frontend:**
  - After frontend follow-up 3, Node 22.12 or later is needed to build. Check Vercel → Settings → Build and Deployment → Node.js Version is 22.x or later before merging it.
  - Fonts no longer load from Google.

## 4. Updated merge-day checklist

The full list, with a check and an undo for every step, is
`docs/MERGE_DAY_CHECKLIST.md` in the backend. The order:

1. **A. Environment only:** Render variables (new `SECRET_KEY`, `DJANGO_DEBUG=False`, …), start command, Vercel variables.
2. **B. Merge and deploy one at a time, checking after each.**
   1. Frontend remediation 1
   2. Backend remediation 1
   3. Build command, backups and branch protection
   4. Pre-flight SQL on production
   5. Backend remediation 2, then frontend remediation 2, then backend remediation 3
   6. Backend follow-up 1, then set Health Check Path `/healthz`
   7. Frontend follow-up 1
   8. Backend follow-up 2
   9. Backend follow-up 3
   10. Frontend follow-up 2, only after 8 and 9
   11. Backend follow-up 4
   12. Frontend follow-up 3, after checking that Vercel builds with Node 22.x
   13. `smoke_check.py`
   14. Optionally, `e2e/`
3. **C. After deploy:**
   - restore drill;
   - throttle check (`--verify-throttle`);
   - uptime monitor on `/healthz` and Sentry alerts;
   - CSP to enforcing after clean days;
   - measure `DRF_NUM_PROXIES`.
4. **D. Before real children's data:**
   - counsel reviews `docs/legal/`;
   - Gemini paid tier and data processing terms;
   - DPA with the school and notices;
   - ODPC registration;
   - DPIA;
   - SPF, DKIM and DMARC, checked with `check_email_dns.py`;
   - two-family messaging check;
   - guardian verification procedure;
   - hosting tier;
   - delete the stray branch.

Frontend follow-up 3 (toolchain) is ROLLOUT step 15. It has no backend
dependency; it only needs the Node setting above.

## 5. Verification evidence

All checks ran locally, against scratch SQLite or local Postgres 16, with
`DATABASE_URL` unset. Nothing ran against production.

- **Red, then green:** each item's new tests were run against the code
  before the fix. They failed for the expected reason, then passed after the
  fix.
- **Backend baseline** (remediation-phase-3; the isolation, approvals,
  guardians and messaging labels): 131 tests OK. The full suite was green in
  CI on the same commit.
- **Backend full suite, serial, on `claude/followup-4-docs-and-scripts`:**
  **716 tests, OK**, in 2,035 s (608 existing plus the 108 added here).
  Also run in parallel in CI on every branch.
- **Backend CI** (GitHub Actions: tests on Postgres, `check --deploy`,
  `makemigrations --check`, pip-audit, lint): green on the tip of all four
  backend branches. The latest run is on `3bd6f5e`.
- **Backend isolation, approvals, guardians and messaging gates:**
  - after follow-up 1: 341 OK;
  - after B-4: 454 OK;
  - communications and messaging after B-9: 90 OK.
- **Attack harness** (from the audit): 158 OK and 5 FAIL. The 5 are the same
  harness-side artefacts explained in REMEDIATION_REPORT. Cross-tenant: 64/64.
- **Deploy and migration checks:**
  - `check --deploy --fail-level ERROR` with production-like settings: only `security.W021` (HSTS preload, a deliberate choice).
  - `makemigrations --check`: no changes.
  - `pip-audit -r requirements.txt`: no known vulnerabilities.
- **Migrations:**
  - Empty database: all apply, in CI and locally.
  - Local Postgres copy of the seeded 1,200-student and 6,002-grade database: `communications.0004` and `students.0012` applied in 1.56 s.
  - Both reverse (`students 0011`, `communications 0003`) and reapply cleanly.
- **Frontend**, from clean checkouts (`npm ci`, tests, build, `npm audit --omit=dev`):

  | Branch | Tests | Build | `npm audit --omit=dev` |
  |---|---|---|---|
  | follow-up 1 | 40 passed | passes | 0 vulnerabilities |
  | follow-up 2 | 63 passed | passes | 0 vulnerabilities |
  | follow-up 3 | 63 passed | passes, 0.8 s | 0 vulnerabilities |

  Follow-up 3's `npm audit` including dev dependencies: 0 vulnerabilities.
  Frontend CI is green on all three branches.
- **Browser checks**, local stack with the `vercel.json` headers:
  - **F-1:**
    - the reset message is identical for known and unknown emails;
    - the link works, the new password works and the old one doesn't;
    - the other device's tokens get 401;
    - the link can't be reused (400).
  - **F-2:** 0 CSP reports and no foreign hosts across admin (17 tabs), teacher (14) and parent (4). Fonts load from the site itself (192 kB in total), with preload starting at about 15 ms.
  - **F-3:** two tabs × {no Web Locks, throwing Web Locks, native} gave one refresh each, with rotation.
  - **F-4/F-5:** paged requests were seen; the time zone change persists and moves the dashboard date.
  - **B-9:**
    - the test alert reached 7 staff email addresses with a "TEST: URGENT:" subject and no parent;
    - the teacher banner shows "Test"; the parent sees none;
    - the 6th test alert of the day was refused.
- **Per-role Playwright smoke** (`e2e/` on the final branches, local stack,
  `--allow-mutations`): **6/6 passed**:
  - identity for admin, teacher and parent;
  - the two-family contact check;
  - password reset;
  - single refresh with rotation.
- **Scripts:**
  - `smoke_check.py` against the local stack: 21 checks, 0 failed, 3 warnings (HTTP-only locally; CSP report-only). Throttle 429 on attempt 11.
  - Pointed at a closed port it exits 1.
  - Both scripts' failure paths are covered by tests (broken headers, DNS timeouts, missing records).
- **Secrets and personal data:** a grep of both diffs for keys, tokens,
  passwords and real email addresses was clean. Only
  `*.example`/`example.com` addresses and the local demo password are used,
  and only in local scripts.
- **Legal drafts:** reviewed as a lawyer would read them. Every statement
  about the law carries [VERIFY], with no section numbers or fine amounts.
  One factual error (what parents see after a child is deactivated) was
  found against the code and corrected.

## 6. Decisions

Where the brief left a choice, I took the safer option:

1. **B-1 paging:**
   - Conversations are paged always, because the shipped frontend already reads both shapes.
   - Other lists are paged only on request, so the frontend still in production keeps working mid-rollout.
2. **B-2:** over-limit rows are deferred, not failed, and nothing is sent
   for them. The limits are checked before recording, so a deferred row
   doesn't use up quota.
3. **B-5:** the refusal looks the same as for an unknown user, so it doesn't
   reveal that the other parent exists. Staff conversations are unchanged.
4. **B-6:**
   - `/healthz` bypasses host, CORS and throttling (it is first in the middleware) and returns no detail beyond ok or degraded and a short commit hash.
   - The commit is shown only if it looks like a hash.
5. **B-7:** without the override, the seeder exits 0 with a message, so a
   build command that still calls it doesn't break the deploy.
6. **B-9:**
   - Every alert is emailed (the checkbox was a way to miss people). Email goes after commit, in the background.
   - The limits refuse with a clear "try again in about N hours".
   - Test alerts can't reach parents.
7. **B-4:** the default is `Africa/Nairobi`, the zone all current schools
   use. Only admins can change it. Stored dates are unchanged.
8. **F-3:** where Web Locks are missing or broken, a short localStorage lease
   gives the same single refresh. If it goes stale (a tab closes mid-refresh)
   it expires after 10 s.
9. **F-6:** the upgrade went on a separate branch last in the order, so it
   can be held back without blocking anything else.
10. **B-13:** the legal texts could not be opened from this environment, so
    no section is cited. Every legal claim is [VERIFY], and the drafts say
    so at the top.
11. **Stray branch:** tried once. The proxy refused, and I did not retry.

## 7. Additional observations

Found along the way; not fixed, because they are outside the list:

1. **Parents still see a child after the school marks the child as left.**
   `GuardianStudentViewSet` doesn't filter out inactive (left) students. The
   guardian procedure now tells schools to untick the child as well. A code
   change is a product and legal decision (retention, counsel question 7).
2. **Parent `/api/me/` returns 403** on the parent identity path. This
   existed before and was already noted in the remediation. The frontend
   handles it; it shows as one 403 in the browser console.
3. **Google Fonts** were unreachable from this environment's browser
   (certificate error through the proxy). The "before" size was measured
   with curl. It doesn't matter now that fonts are self-hosted.
4. **Local-only warning:** `UserWarning: No directory at …/staticfiles/`
   appears in test output because tests don't run `collectstatic`. It is
   harmless.
5. **Lint:** `ruff check --select F` is clean. Wider rule sets were not
   turned on, to avoid churn. CI reports lint without blocking.

## 8. Could not verify

- **Anything against production.** Not allowed and not attempted. No
  read-only smoke check of the live URLs was run either: they aren't
  recorded in the repositories or the audit. Run `smoke_check.py` yourself
  (checklist B15).
- **Real email delivery, SPF, DKIM and DMARC for your domain.** This needs
  your domain, your provider and live SMTP. The DNS script was tried
  read-only against a public domain, where it correctly reported a DNS
  timeout and a missing DKIM selector as failures.
- **Real devices and real browsers other than Chromium.** Web Locks failures
  were simulated in Chromium.
- **The legal primary texts.** The environment's network policy refused
  kenyalaw.org, new.kenyalaw.org, www.odpc.go.ke and kentrade.go.ke. The
  drafts need an advocate's check of every [VERIFY].
- **Vercel's Node version.** Check the project setting before merging
  frontend follow-up 3.
- **The occasional double refresh with native Web Locks.** One run of 21
  showed 2 refresh calls; 20 runs in a row then showed 1. It could not be
  reproduced, and rotation kept the session valid either way.

## 9. Owner-only (not done, by design)

- **Hosting settings:** Render, Vercel and GitHub environment variables and
  secrets; Render Health Check Path; start and build commands.
- **Backups and data:** backups and restore drills against production;
  pre-flight SQL on production.
- **GitHub:**
  - branch protection on `master` and `main`;
  - making the repositories private;
  - deleting `claude/ci-demo-broken-test`.
- **Merging and deploying every pull request,** in the order above.
- **Legal and compliance:**
  - Gemini paid tier and Google's data processing terms;
  - DPAs with schools;
  - ODPC registration;
  - counsel review.
- **Accounts:** uptime monitoring and paid hosting tiers.
- **Email:** DNS records and email-provider settings; live SMTP tests.
- **Devices:** real-device testing.
- **Keys:** rotating `SECRET_KEY`, `GEMINI_API_KEY` and any other key.
- **Network access (optional):** to let a future session read the legal
  sources, allow `kenyalaw.org`, `new.kenyalaw.org`, `www.odpc.go.ke` and
  `kentrade.go.ke` in the environment's network settings.
