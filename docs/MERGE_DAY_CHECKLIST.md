# Merge-day checklist

One list, in the order you'll act, from the readiness fixes to the first
real children's data. Print it and tick as you go. Details for each step:
[HUMAN_ACTIONS.md](HUMAN_ACTIONS.md) (H-numbers) and [ROLLOUT.md](ROLLOUT.md)
(why the order matters). "Undo" is how to roll back if the check fails.

Two read-only helpers from your own computer, in the backend repository:

```bash
python scripts/smoke_check.py --api https://<backend> --frontend https://<frontend>
python scripts/check_email_dns.py <your email domain> --dkim-selector <selector> --provider <provider>
```

Never paste a secret into a pull request, issue or chat.

---

## A. Before merging anything (environment only; nothing deploys)

- [ ] **A1. Render environment (H-3).** Render → backend service → Environment: `DJANGO_DEBUG=False`, a **new** `SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`, the SMTP settings, `DEFAULT_FROM_EMAIL`, `SENTRY_DSN`, `DJANGO_ADMIN_PATH` (something hard to guess). Leave `DEMO_PASSWORD` and `ALLOW_DEMO_SEED` **unset**. Tell staff they'll sign in again once.
  *Check:* locally, with the same values exported, `python manage.py check --deploy --fail-level ERROR` passes. *Undo:* nothing runs yet.
- [ ] **A2. Start command (H-4).** Settings → Start Command exactly `gunicorn housemaster.wsgi`; `WEB_CONCURRENCY=1`.
  *Check:* comes with B2 (log shows `Using worker: gthread`).
- [ ] **A3. Vercel environment (H-11).** Settings → Environment Variables (Production and Preview): `VITE_API_BASE_URL`, `VITE_SENTRY_DSN`, `VITE_SENTRY_ENVIRONMENT`.
  *Check:* Deployments → ⋯ → Redeploy on the current build succeeds. *Undo:* remove the variables.

## B. Merge and deploy, one step at a time

Merge each pull request, wait for the deploy, do its check, then go on.

- [ ] **B1. Frontend remediation phase 1** (frontend `claude/remediation-phase-1`).
  *Check:* sign in and out as an admin, a teacher and a parent. *Undo:* revert the merge on `main`.
- [ ] **B2. Backend remediation phase 1** (backend `claude/remediation-phase-1`), only after B1 is live.
  *Check:* deploy log shows `gthread` and no `ImproperlyConfigured`; a parent's "New message" list shows only their children's teachers and admins. *Undo:* revert the merge (a failed build keeps the old version).
- [ ] **B3. Build command, backups, branch protection (H-5, H-2, H-1, H-7).** Build command as in H-5, `THROTTLE_CACHE=db`; read-only backup login; backup secrets; run the backup workflow; protect `master` and `main`.
  *Check:* backup run ends "OK: … restored and match"; a direct push to `master` is refused.
- [ ] **B4. Production data pre-checks (H-6).** `psql "<read-only string>" -f scripts/preflight_range_checks.sql` and `-f scripts/preflight_duplicate_emails.sql`.
  *Check:* every count is 0 (fix rows first if not).
- [ ] **B5. Backend remediation phase 2**, then **B6. Frontend remediation phase 2**, then **B7. Backend remediation phase 3**.
  *Check each:* marks, attendance and a long conversation open; every page loads with no console errors; the admin site answers at your `DJANGO_ADMIN_PATH`, not `/admin/`. *Undo:* revert that merge.
- [ ] **B8. Backend follow-up 1** (`claude/followup-1-hardening`), then set Render → Settings → **Health Check Path** to `/healthz`.
  *Check:* `curl -s https://<backend>/healthz` shows `"status": "ok"` and a commit matching `master`'s latest. *Undo:* revert; clear the Health Check Path.
- [ ] **B9. Frontend follow-up 1** (`claude/followup-1-fixes`).
  *Check:* "Forgot password" with your own email sends a reset link; the link lets you set a new password. *Undo:* revert.
- [ ] **B10. Backend follow-up 2** (`claude/followup-2-lists-and-timezone`). Adds a column with a default (can't fail on existing data).
  *Check:* Messages, Reports and Approvals open. *Undo:* revert (`migrate students 0011` if needed).
- [ ] **B11. Backend follow-up 3** (`claude/followup-3-communications`). Adds a column with a default.
  *Check:* comes with B12. *Undo:* revert (`migrate communications 0003` if needed).
- [ ] **B12. Frontend follow-up 2** (`claude/followup-2-lists-and-timezone`), only after B10 and B11.
  *Check:* Setup → School time zone shows `Africa/Nairobi`; Urgent alerts → **Send a test alert to staff** reaches staff (banner and email marked TEST) and no parent. *Undo:* revert.
- [ ] **B13. Backend follow-up 4** (`claude/followup-4-docs-and-scripts`): documents and scripts only.
- [ ] **B14. Frontend follow-up 3** (`claude/followup-3-toolchain`): newer build tools and the `e2e/` smoke tests. First check Vercel → Settings → Build and Deployment → Node.js Version is 22.x or later.
  *Check:* the deploy builds; pages look and work as before. *Undo:* revert.
- [ ] **B15. Smoke check.** Run `scripts/smoke_check.py` against production.
  *Check:* 0 failed. Warnings expected: report-only CSP until C4.
- [ ] **B16. Browser smoke tests (optional).** In the frontend repository: `cd e2e && npm install && node run.mjs --frontend https://<frontend> --api https://<backend>` with test accounts in `E2E_*` variables (e2e/README.md). Read-only unless you add `--allow-mutations`.
  *Check:* all pass (roles without accounts are skipped).

## C. After deploy

- [ ] **C1. Restore drill (H-1).** Follow the checklist at the end of [BACKUPS.md](BACKUPS.md); fill in the RPO/RTO table.
  *Check:* restored row counts match.
- [ ] **C2. Rate limits.** `python scripts/smoke_check.py --api … --frontend … --verify-throttle <an address you own>` (locks that address out for up to an hour).
  *Check:* "Login throttle PASS, 429 on attempt 11" or earlier.
- [ ] **C3. Uptime and alerts (H-10).** An uptime monitor on `https://<backend>/healthz` and on the frontend; Sentry alerts to a phone.
  *Check:* pausing the monitor's target (or a test alert) reaches your phone.
- [ ] **C4. CSP to enforcing (H-12)** after a few clean days: rename `Content-Security-Policy-Report-Only` to `Content-Security-Policy` in the frontend's `vercel.json`, through a pull request.
  *Check:* every page still works; smoke check shows "enforcing". *Undo:* rename it back.
- [ ] **C5. Measure `DRF_NUM_PROXIES`** ([ENVIRONMENT.md](ENVIRONMENT.md)) and set it.
  *Check:* `check --deploy` no longer warns W001.

## D. Before real children's data

- [ ] **D1. Counsel.** A Kenyan data-protection advocate reviews [legal/](legal/README.md), starting with [QUESTIONS_FOR_COUNSEL.md](legal/QUESTIONS_FOR_COUNSEL.md). The drafts are not legal advice.
- [ ] **D2. AI terms (H-8).** Gemini on a paid no-training tier, Google's data-processing terms accepted, new `GEMINI_API_KEY` on Render.
- [ ] **D3. Agreements and notices (H-8).** Data processing agreement signed with the school; HouseMaster's privacy notice published; the school's notice adapted from the template and linked as its privacy contact; sub-processor regions and transfer grounds filled in.
- [ ] **D4. ODPC registration** ([ODPC_REGISTRATION_GUIDE.md](legal/ODPC_REGISTRATION_GUIDE.md)).
  *Check:* certificate downloaded; renewal in your calendar.
- [ ] **D5. DPIA** ([DRAFT_DPIA.md](legal/DRAFT_DPIA.md)) completed and signed by the school.
- [ ] **D6. Real email delivery.** Set up SPF, DKIM and DMARC with your email provider (it shows the records and the DKIM **selector** on its "domain authentication" page), then `python scripts/check_email_dns.py <domain> --dkim-selector <selector> --provider <provider>`.
  *Check:* 0 failed; then send yourself an invite and a password reset from the live site and confirm they arrive in the inbox, not spam.
- [ ] **D7. Real parent messaging check** with two parent accounts of different families at a test school: each sees only their own child, can message only that child's teachers and the admins, and never sees the other parent. The frontend's `e2e` suite automates it (`E2E_PARENT_*`, `E2E_PARENT2_*`; add `--allow-mutations` for the refused-message step, test accounts only).
- [ ] **D8. Guardian checks.** The school adopts [SCHOOL_guardian_verification_procedure.md](legal/SCHOOL_guardian_verification_procedure.md) before linking any parent.
- [ ] **D9. Hosting (H-10).** Render Starter or higher (then `WEB_CONCURRENCY=2`) and Neon Launch or higher before a second school.
- [ ] **D10. Stray branch.** Delete `claude/ci-demo-broken-test` on GitHub (Branches → bin icon).
