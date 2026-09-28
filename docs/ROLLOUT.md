# Rolling out the readiness fixes

The fixes from the 2026-09-28 production readiness audit arrive as pull
requests on both repositories. Merging to `master` (backend) or `main`
(frontend) deploys to production, so merge them **in this order**, one step
at a time, and do the checks after each step before going on.

Each pull request is written to be safe at its own position in this list
and not before it.

| Step | What | Repository / branch |
|---|---|---|
| 0 | Owner sets environment variables | Render and Vercel dashboards (H-3, H-4, H-11) |
| 1 | Frontend compatibility release | frontend `claude/remediation-phase-1` |
| 2 | Backend Phase 1 | backend `claude/remediation-phase-1` |
| 3 | Owner turns on backups, build steps and branch protection | H-1, H-2, H-5, H-7 |
| 4 | Owner checks production data | H-6 |
| 5 | Backend Phase 2 | backend `claude/remediation-phase-2` |
| 6 | Frontend Phase 2 | frontend `claude/remediation-phase-2` |
| 7 | Backend Phase 3 | backend `claude/remediation-phase-3` |
| 8 | Owner flips the CSP to enforcing after a few clean days | H-12 |

Backend branches are stacked: Phase 2 contains Phase 1, and Phase 3
contains both. Merge them in order, and each pull request's diff shrinks to
its own changes once the one before is merged. The same goes for the two
frontend branches.

---

## Step 0 · Environment first

Do H-3, H-4 and H-11 in [HUMAN_ACTIONS.md](HUMAN_ACTIONS.md). Nothing is
deployed by this step, and the current production code ignores the new
variables. Tell staff that everyone will need to sign in again once (the
new `SECRET_KEY`).

## Step 1 · Frontend compatibility release

Makes the frontend ready for the backend changes while behaving exactly as
before against today's backend:

- stores the new refresh token when a token refresh returns one (needed once
  refresh tokens rotate), and makes all requests that hit an expired token
  at once share one refresh, across tabs as well;
- the Sign out button also tells the backend to retire the session;
- reads lists in either shape (a plain list, or a page with `results`);
- a production build fails if `VITE_API_BASE_URL` is missing;
- adds frontend tests and CI.

**Watch after deploy:** sign in, move around, sign out, sign in as a parent.
Leave a tab open for over an hour and use it again (the token refresh
path). Sentry shows no new frontend errors.

**Rollback:** revert the merge on `main`; Vercel redeploys the previous
build. No data is involved.

## Step 2 · Backend Phase 1

F-01, F-02 (scripts and docs), F-03, F-04, F-05, F-06, F-07, F-08, E-1, E-4.

**Before merging:** step 0 is done and step 1 is live. Without step 1, the
old frontend would reuse a retired refresh token and sign people out after
about an hour.

**What changes for users:** everyone signs in again once (new
`SECRET_KEY`). Parents only see their children's teachers and the admins in
"New message". Wrong passwords are limited per email and per address.
Sessions end when a password is changed or reset. AI buttons answer "busy,
try again" instead of hanging.

**Watch after deploy:**
- The Render deploy log shows `Using worker: gthread` and no
  `ImproperlyConfigured`.
- Sign in as an admin, a teacher and a parent; the parent's "New message"
  list shows only their children's teachers and the admins.
- Generate one AI report comment; it uses the student's first name.
- Sentry: no new backend errors.
- Measure `DRF_NUM_PROXIES` now if it wasn't done in step 0
  ([ENVIRONMENT.md](ENVIRONMENT.md)).

**Migrations:** `accounts.0012_usersecurity` (new table, one row per
user) and simplejwt's `token_blacklist` tables. Both only add tables.

**Rollback:** revert the merge on `master`. The added tables can stay; the
old code ignores them. If the new build fails because a variable is
missing, Render keeps the previous version running: fix the variable and
redeploy. Rolling back re-opens F-01 and F-04, so fix forward if at all
possible.

## Step 3 · Backups, build steps, branch protection

H-1, H-2, H-5, H-7. After H-5, `THROTTLE_CACHE=db` keeps rate-limit counts
across restarts. After H-7, every later step goes through a pull request
with green CI.

## Step 4 · Check production data

H-6. Both pre-flight SQL files must report 0 before step 5.

## Step 5 · Backend Phase 2

F-09 to F-14, F-18, F-19 and the invite part of F-12.

**Before merging:** step 4 reported zeros. The migrations re-check the same
things and stop with row IDs (never emails) if anything is wrong, which
fails the deploy and keeps the old version running. On PostgreSQL each
migration commits on its own, so a stopped deploy can leave the unique
email index added while the grade constraints wait; the old code runs fine
with it. Fix the rows the message names and deploy again.

**API change:** grades, attendance, the activity log and conversation
messages now come back a page at a time (`{count, next, previous, results}`).
The step 1 frontend already reads both shapes, so this is safe after step 1.

**Watch after deploy:** open a class's marks and attendance, the activity
log and a long conversation; download a class list export; check "today"
on the dashboard around midnight Nairobi time if convenient.

**Rollback:** revert the merge. The Phase 2 migrations only add
constraints and an index; reverting the code while they stay is safe, or
reverse them with `manage.py migrate <app> <previous migration>` if needed
(each has a reverse operation).

## Step 6 · Frontend Phase 2

Report-only Content-Security-Policy and security headers (`vercel.json`),
and page-by-page loading for the long lists.

**Watch after deploy:** every page loads; the browser console shows no
errors. Report-only CSP messages are expected to be none, but they don't
break anything.

**Rollback:** revert the merge on `main`.

## Step 7 · Backend Phase 3

F-16 (fuller family export, also as JSON; removal also scrubs subject
comments and conversations about the child; a retention command that is off
and a dry run by default), F-17 (configurable admin path, admin login
throttle, `sync_superuser` no longer resets the password on each deploy) and
F-20 documentation.

**Before merging:** decide the admin path and set `DJANGO_ADMIN_PATH` on
Render (for example `manage-7f3c2a/`). If you rely on `sync_superuser` to
reset a forgotten password, read the note in [ENVIRONMENT.md](ENVIRONMENT.md)
about `SYNC_SUPERUSER_RESET_PASSWORD`.

**Rollback:** revert the merge. Phase 3 has no migrations.

No frontend change is needed: the existing Data protection panel already
calls the export and removal endpoints.

## Step 8 · Enforce the CSP

H-12, after several clean days of step 6.

---

# The follow-up releases

After step 8 (or alongside it, once step 7 is live), the follow-up pull
requests go in this order. The printable version of the whole sequence is
[MERGE_DAY_CHECKLIST.md](MERGE_DAY_CHECKLIST.md).

| Step | What | Repository / branch | Needs first |
|---|---|---|---|
| 9 | Backend follow-up 1: reset contract test, bulk-import invite limits, own bucket for reset confirmation, no mixed families in direct messages, `/healthz`, demo seed guard, cleanups | backend `claude/followup-1-hardening` | step 7 |
| 10 | Frontend follow-up 1: "Forgot password" fixed, self-hosted fonts and tighter CSP, refresh without Web Locks, deferred import rows | frontend `claude/followup-1-fixes` | step 6 (works with any backend) |
| 11 | Backend follow-up 2: the remaining long lists paged (conversations always; reports, announcements, change requests when asked), per-school time zone | backend `claude/followup-2-lists-and-timezone` | step 9 |
| 12 | Backend follow-up 3: urgent alerts always emailed, per-school alert limits, test alerts, class-message limit | backend `claude/followup-3-communications` | step 11 |
| 13 | Frontend follow-up 2: paged screens, School time zone in Setup, test alerts | frontend `claude/followup-2-lists-and-timezone` | steps 11 and 12 |
| 14 | Backend follow-up 4: merge-day checklist, smoke and email-DNS scripts, legal drafts | backend `claude/followup-4-docs-and-scripts` | step 12 (documents and scripts only) |

## Step 9 · Backend follow-up 1

**After deploy:** set Render → Settings → Health Check Path to `/healthz`
(H-4). If `DEMO_PASSWORD` is set on Render, the demo schools are no longer
created or rebuilt there (the deploy still succeeds); remove the variable.

**Rollback:** revert the merge. No migrations.

## Step 10 · Frontend follow-up 1

**Watch:** "Forgot password" sends a reset email; pages look the same (the
fonts are now served by the app); no CSP reports in the console.

**Rollback:** revert the merge.

## Step 11 · Backend follow-up 2

**Migration:** `students.0012_school_timezone` adds `School.timezone` with
the default `Africa/Nairobi`, so it can't fail on existing rows and every
school keeps today's behaviour. No pre-check needed.

**API change:** conversations come back a page at a time; the frontend
already deployed follows the pages. Reports, announcements and change
requests are unchanged unless a client asks for a page.

**Rollback:** revert; `python manage.py migrate students 0011` removes the
column if wanted (not needed: older code ignores it).

## Step 12 · Backend follow-up 3

**Migration:** `communications.0004_urgent_alert_is_test` adds a boolean
with a default. No pre-check needed.

**Behaviour change:** every urgent alert is emailed as well as shown in the
app (the old "also email" box stops mattering); at most 10 alerts and 5
test alerts per school per day (`ALERT_SCHOOL_RATE`,
`ALERT_TEST_SCHOOL_RATE`).

**Rollback:** revert; `migrate communications 0003` if wanted.

## Step 13 · Frontend follow-up 2

**Before merging:** steps 11 and 12 are live. Against an older backend the
time-zone setting would appear to save but change nothing, and a test alert
would go to staff as an ordinary alert titled "Test alert".

**Watch:** Setup shows School time zone; Approvals, Reports and
Announcements show "Show N more" on long lists; a test alert reaches staff
only.

**Rollback:** revert the merge.

## Step 14 · Backend follow-up 4

Documents and scripts only; nothing changes in the running app.
