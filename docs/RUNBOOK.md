# Incident response runbook

For anything that stops schools working or might expose data. Keep a copy
of this page somewhere you can read when the app, GitHub or your laptop is
down (a printout or a phone note).

## Contacts (fill in and keep current)

| Role | Name | Phone | Email |
|---|---|---|---|
| Maintainer | | | |
| Backup maintainer (has repo, Render, Neon, Vercel and Sentry access) | | | |
| Counsel / data-protection adviser | | | |
| Pilot school head | | | |
| Pilot school data-protection officer | | | |

Provider support: Render (dashboard → Help), Neon (console → Support),
Vercel (dashboard → Help), Google Cloud (Gemini billing console), your
SMTP provider.

## 1. Detect

Signals: a Sentry alert, an uptime-monitor alert, a message from a school,
a failed-workflow email from GitHub (backups, CI).

Start an incident note straight away (a dated document): the time, who
reported it, what they saw. Add to it as you go.

## 2. Triage (within 30 minutes)

Pick one:

- **Outage** — the app or a feature doesn't work.
- **Data integrity** — data is wrong, missing or duplicated.
- **Data exposure** — someone may have seen or taken data they shouldn't
  have. **Any suspected exposure of children's data is Severity 1**:
  drop other work.

## 3. Contain

**Data exposure**

1. Stop further access:
   - To sign out *everyone*, set a new `SECRET_KEY` on Render (generate
     with `python -c "import secrets; print(secrets.token_urlsafe(64))"`)
     and save. Every session ends on the redeploy.
   - To sign out *one* person, reset their password or deactivate their
     account in the app (both end all their sessions immediately).
   - If a feature is leaking, revert the change that introduced it (a pull
     request reverting the merge) or ship a fix that switches the endpoint
     off.
2. Preserve evidence **before** logs roll over: download the Render logs
   for the period, export the relevant Sentry issues, and note the
   activity-log entries (Admin → Activity).
3. If a secret may have leaked (API key, SMTP password, database
   password), rotate it at the provider, then update Render.

**Data integrity**

1. Stop more damage: if a school is making it worse by using the feature,
   ask them to pause, or revert the change.
2. Take a backup now: **Actions → Database backup → Run workflow**.
   Neon's restore window also covers the last few hours.

**Outage**

1. `curl -s https://<backend>/healthz`: `"status": "ok"` means the app
   and database answer; `"degraded"` (503) means the app runs but the
   database doesn't; no answer means the app itself is down or asleep.
   The `commit` field is the first 7 characters of the commit that is
   live, so you can tell whether a deploy actually went out. Then check
   Render (deploy failed? instance sleeping or out of memory?), Neon
   (status page, compute suspended?), Vercel and Sentry.
2. A deploy that fails keeps the previous version running. A bad deploy
   that succeeded: revert the merge on `master` / `main`.

## 4. Assess

Which schools, which records, which time window? Use the activity log
(who changed what), Render logs (requests and errors), Sentry, and the
database (read-only role from BACKUPS.md). Write down what is known and
what isn't.

## 5. Notify

- Tell the affected school's head and data-protection officer **within
  24 hours**, even if the picture is incomplete.
- Counsel decides whether the regulator and parents must be told, and by
  when (for example 72 hours under the Kenya Data Protection Act and UK
  GDPR). The school is usually the one that notifies them; HouseMaster
  supports it with the facts.

## 6. Recover

Fix forward, or restore (docs/BACKUPS.md, "Restoring from a nightly
backup"). Check with `scripts/row_counts.sh` and by opening real records.

## 7. After (within 5 days)

Write a short post-mortem: timeline, root cause, what went well, what
didn't, and actions. Every fixed bug gets a regression test. Share the
summary with the affected school.
