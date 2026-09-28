# Things only the owner can do

These need dashboards, secrets, contracts or repository settings, so the
code changes can't do them. They are in the order to do them. Each ends with
how to check it worked. The deploy order they fit into is in
[ROLLOUT.md](ROLLOUT.md).

Never paste a secret into a GitHub issue, pull request, chat or commit.

---

## H-1 · Switch on the nightly backups (do this first)

**Why:** no backup has ever been taken (F-02).

1. Do **H-2** first to get a read-only connection string.
2. Make a backup passphrase: five or six random words, or
   `openssl rand -base64 32`. Save it in your password manager **before**
   going on. Without it every backup is unreadable.
3. GitHub → **HOUSEMASTER** repository → **Settings → Secrets and variables
   → Actions → New repository secret**:
   - `BACKUP_DATABASE_URL` = the read-only connection string from H-2
   - `BACKUP_PASSPHRASE` = the passphrase
4. Optional but recommended, a copy outside GitHub: create a bucket on any
   S3-compatible storage and add `BACKUP_S3_BUCKET`,
   `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, and
   `BACKUP_S3_REGION` or `BACKUP_S3_ENDPOINT` (details in
   [BACKUPS.md](BACKUPS.md)).
5. **Actions** tab → **Database backup** → **Run workflow**.

**Check:** the run is green and the "Prove the backup restores" step ends
with `OK: … tables and … rows restored and match`. Then do the restore drill
checklist at the bottom of [BACKUPS.md](BACKUPS.md) and fill in the RPO/RTO
table there.

## H-2 · Create the read-only backup login on Neon

1. Neon console → project → **Connect**. Turn **connection pooling off**
   (the host must not contain `-pooler`) and copy the owner's connection
   string.
2. On a computer with `psql` and this repository checked out:

   ```bash
   BACKUP_ROLE_PASSWORD="$(openssl rand -hex 24)"
   psql "<owner direct connection string>" \
     -v backup_password="$BACKUP_ROLE_PASSWORD" -v app_owner=neondb_owner -v dbname=neondb \
     -f scripts/create_backup_role.sql
   ```

   (Use your real owner role and database names if they differ.)
3. Build the backup string: the same direct string with
   `neondb_owner:<owner password>` replaced by
   `housemaster_backup:<BACKUP_ROLE_PASSWORD>`. That is `BACKUP_DATABASE_URL`.

**Check:** `psql "<backup string>" -c "select count(*) from students_student"`
works, and `psql "<backup string>" -c "delete from students_student"` fails
with "cannot execute DELETE in a read-only transaction".

## H-3 · Set the Render environment (before the backend Phase 1 deploy)

**Why:** from Phase 1 the backend refuses to start without these (F-03).
This is a **hard prerequisite**: a Render build with them missing fails,
and Render keeps the old version running.

Render → backend service → **Environment**. Set every variable in the
"Required in production" table of [ENVIRONMENT.md](ENVIRONMENT.md):

- `DJANGO_DEBUG=False`
- `SECRET_KEY` = a **new** key:
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
  The old development key is published in this public repository; if
  production ever used it, anyone could forge logins. A new key signs
  everyone out once, so tell staff beforehand ("you'll need to sign in
  again after 6 pm").
- `DATABASE_URL` (Neon pooled string), `DJANGO_ALLOWED_HOSTS`,
  `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`
- `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`,
  `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`,
  `DEFAULT_FROM_EMAIL`
- `SENTRY_DSN`, `SENTRY_ENVIRONMENT=production`
- `DRF_NUM_PROXIES` after measuring it ([ENVIRONMENT.md](ENVIRONMENT.md),
  "Finding DRF_NUM_PROXIES"); until then leave it unset (the deploy check
  only warns).

**Check:** on your computer, with the same values exported in a shell
(don't save them to a file), `python manage.py check --deploy --fail-level ERROR`
passes. After the deploy, sign in on the live site.

## H-4 · Render start command and processes

Render → backend service → **Settings → Start Command** must be exactly:

```
gunicorn housemaster.wsgi
```

No `--workers`, `--threads`, `--timeout` or `--worker-class` flags: they
would override `gunicorn.conf.py` (F-07). Then set `WEB_CONCURRENCY=1` in
**Environment** (use `2` once on a paid plan with more memory).

**Check:** the deploy log shows `Using worker: gthread`.

Then, once the backend with `/healthz` is deployed (follow-up 1), set
**Settings → Health Check Path** to `/healthz`. Render then only switches
traffic to a new deploy once it answers, and restarts an instance that stops
answering.

**Check:** `curl -s https://<backend>/healthz` prints
`{"status": "ok", "commit": "<7 characters>"}`, and the commit matches the
latest commit on `master` (GitHub shows the first 7 characters).

## H-5 · Render build command

Render → **Settings → Build Command**:

```
pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate --noinput && python manage.py createcachetable && python manage.py flushexpiredtokens && python manage.py check --deploy --fail-level ERROR
```

Keep any extra step you already run (for example `sync_superuser`). Then
set `THROTTLE_CACHE=db` in **Environment**.

- `createcachetable` makes the table the rate limits keep their counts in.
- `flushexpiredtokens` clears expired sign-in records (F-04) on each deploy.
- `check --deploy --fail-level ERROR` stops a deploy whose configuration
  is broken (for example email still going to the console).

**Check:** the build log shows each step succeeding. Ten wrong passwords for
one email on the live site give "Request was throttled" on the next try.

## H-6 · Check production data before the Phase 2 backend deploy

**Why:** Phase 2 adds database rules (unique email addresses, sensible
grade and attendance values). If existing rows break them, the migration
stops with a list of row IDs (never emails), and the deploy fails.

The free tier has no shell, so use `psql` from your computer with the
read-only backup string from H-2 (both files arrive with the Phase 2
backend changes):

```bash
psql "<read-only backup string>" -f scripts/preflight_range_checks.sql
psql "<read-only backup string>" -f scripts/preflight_duplicate_emails.sql
```

Every count must be 0. For rows that aren't, fix them in the app (or the
Django admin) before deploying Phase 2: merge or re-email duplicate
accounts, correct impossible grades, delete or re-date future attendance.
`python manage.py check_duplicate_emails` does the same email check if you
have a shell.

**Check:** both files report 0 for every line.

## H-7 · Protect `master` and `main`

**Why:** today anyone with push access deploys straight to production with
no tests (F-06). Protection makes every change go through a pull request
whose CI checks passed.

Only after the CI workflow has run at least once on each repository (so
GitHub knows the check names), run with the GitHub CLI logged in as the
owner:

```bash
gh api -X PUT repos/rahtatuille-debug/housemaster/branches/master/protection --input - <<'EOF'
{
  "required_status_checks": {"strict": true, "checks": [{"context": "test"}]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF

gh api -X PUT repos/rahtatuille-debug/housemaster-frontend/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": {"strict": true, "checks": [{"context": "build"}]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

`required_approving_review_count: 0` requires a pull request but no second
reviewer, which suits a one-person team. `enforce_admins: true` applies the
rule to you too, so an emergency fix also goes through CI; set it to
`false` if you want to be able to bypass it.

**Check:** `gh api repos/rahtatuille-debug/housemaster/branches/master --jq .protected`
prints `true`, and a direct `git push` to `master` is refused.

## H-8 · AI provider terms, agreements, privacy notices and ODPC registration (legal)

Drafts for all of this are in [legal/](legal/README.md). They are **drafts,
not legal advice**: the Kenyan primary texts couldn't be read while they
were written, so every legal point is marked [VERIFY]. Have a Kenyan
data-protection advocate review them first, starting with
[QUESTIONS_FOR_COUNSEL.md](legal/QUESTIONS_FOR_COUNSEL.md).

1. Move the Gemini API key to a **paid** tier whose terms say prompts are
   not used for training, and accept Google's data-processing terms.
   Replace `GEMINI_API_KEY` on Render. (Sub-processors:
   [SUBPROCESSORS.md](legal/SUBPROCESSORS.md); fill in each region and
   transfer ground marked [TO CONFIRM].)
2. Sign a data-processing agreement with the pilot school:
   [DRAFT_data_processing_agreement.md](legal/DRAFT_data_processing_agreement.md).
3. Publish HouseMaster's privacy notice
   ([DRAFT_privacy_notice_housemaster.md](legal/DRAFT_privacy_notice_housemaster.md))
   and give the school the template for its own
   ([DRAFT_school_privacy_notice_template.md](legal/DRAFT_school_privacy_notice_template.md)),
   including the AI transfer described in [AI_DATA_FLOW.md](AI_DATA_FLOW.md).
4. Help the school complete its DPIA ([DRAFT_DPIA.md](legal/DRAFT_DPIA.md))
   and adopt the guardian checks
   ([SCHOOL_guardian_verification_procedure.md](legal/SCHOOL_guardian_verification_procedure.md)).
5. Register with the ODPC:
   [ODPC_REGISTRATION_GUIDE.md](legal/ODPC_REGISTRATION_GUIDE.md).

**Check:** counsel has answered QUESTIONS_FOR_COUNSEL.md; the DPA is signed
by both sides; the notice is published at a public URL and set as the
school's privacy contact link; the ODPC certificate is downloaded and its
expiry is in your calendar.

## H-9 · Repository visibility and the old key

Decide whether the repositories should be private. Note: on the Vercel
Hobby plan, deploys from a private repository have been blocked in the
past, so check the current Vercel plan rules before switching. Either way,
**rotate `SECRET_KEY`** (H-3): the old development key is public.

## H-10 · Hosting, uptime and alerts (before a second school)

- Upgrade Render to a paid instance (no sleeping, more memory; then
  `WEB_CONCURRENCY=2`) and Neon to a plan with a longer restore window.
- Add an uptime monitor (for example UptimeRobot, free) on the backend's
  `https://<backend>/healthz` (expects 200 and `"status": "ok"`; 503 means
  the database isn't answering) and on the frontend, alerting to a phone.
- In Sentry, route new-issue and spike alerts to a phone (email + mobile app).

## H-11 · Set the Vercel environment (before the frontend compat deploy)

Vercel → project → **Settings → Environment Variables**:

- `VITE_API_BASE_URL` = the Render backend URL, for **Production** (and
  **Preview** if you use preview deployments). From the compat release on, a
  production build **fails** without it.
- `VITE_SENTRY_DSN` and `VITE_SENTRY_ENVIRONMENT` (`production` /
  `preview`).

**Check:** redeploy the current production build (Deployments → ⋯ →
Redeploy); it succeeds and the app still signs in.

## H-12 · Turn the Content-Security-Policy from report-only to enforcing

The frontend Phase 2 release sends `Content-Security-Policy-Report-Only`.
It blocks nothing; browsers only report what the policy *would* block.

1. After the release, use the app for a few days on a phone and a laptop,
   visiting every page (including report card PDFs), with the browser's
   developer console open where you can. Look for messages starting
   "[Report Only] Refused to…".
2. If there are none (or only ones you understand and have fixed), edit
   `vercel.json` in the frontend repository: rename the header key
   `Content-Security-Policy-Report-Only` to `Content-Security-Policy`
   (same value), and deploy through a pull request.

**Check:** the response headers of the live site show
`Content-Security-Policy`, and every page still works.
