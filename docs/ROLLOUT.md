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
| 8 | Frontend Phase 3 | frontend `claude/remediation-phase-3` |
| 9 | Owner flips the CSP to enforcing after a few clean days | H-12 |

Backend branches are stacked: Phase 2 contains Phase 1, and Phase 3
contains both. Merge them in order, and each pull request's diff shrinks to
its own changes once the one before is merged. The same goes for the
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
fails the deploy and keeps the old version running.

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

F-16 (export and anonymise one child's data, retention command, dry-run by
default), F-17 (configurable admin path, admin login throttle,
`sync_superuser` no longer resets the password on each deploy) and F-20
documentation.

**Before merging:** decide the admin path and set `DJANGO_ADMIN_PATH` on
Render (for example `manage-7f3c2a/`). If you rely on `sync_superuser` to
reset a forgotten password, read the note in [ENVIRONMENT.md](ENVIRONMENT.md)
about `SYNC_SUPERUSER_RESET_PASSWORD`.

**Rollback:** revert the merge. The Phase 3 migration only adds columns.

## Step 8 · Frontend Phase 3

Buttons for "Export this student's data" and "Anonymise this student" on
the student profile (admins only).

## Step 9 · Enforce the CSP

H-12, after several clean days of step 6.
