# Pilot readiness checklist (one school, real data)

Everything here must be ticked before the first real child's data goes in.
References are to [HUMAN_ACTIONS.md](HUMAN_ACTIONS.md) (H-) and the audit
findings (F-).

## Code

- [ ] Frontend compatibility release is live ([ROLLOUT.md](ROLLOUT.md), step 1).
- [ ] Backend Phase 1 is live (step 2) and its CI run was green.
- [ ] CI runs on every pull request, and `master` / `main` are protected (H-7).

## Configuration

- [ ] Render environment set and checked (H-3): `DJANGO_DEBUG=False`, a new
      `SECRET_KEY`, `DATABASE_URL`, `DJANGO_ALLOWED_HOSTS`,
      `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`, SMTP settings,
      `DEFAULT_FROM_EMAIL`, `SENTRY_DSN`. Keep a screenshot with the values
      hidden.
- [ ] `check --deploy --fail-level ERROR` passes in the Render build (H-5).
- [ ] `DRF_NUM_PROXIES` measured and set; `LOG_CLIENT_IP_DEBUG` removed
      ([ENVIRONMENT.md](ENVIRONMENT.md)).
- [ ] `THROTTLE_CACHE=db` set and `createcachetable` in the build (H-5).
- [ ] Start command is plain `gunicorn housemaster.wsgi` and the log shows
      `Using worker: gthread` (H-4).
- [ ] Vercel `VITE_API_BASE_URL` and Sentry variables set (H-11).

## Data safety

- [ ] Nightly backup green, including "Prove the backup restores" (H-1, H-2).
- [ ] One full restore drill done and the RPO/RTO table in
      [BACKUPS.md](BACKUPS.md) filled in.
- [ ] A backup copy exists outside GitHub.

## Checked by hand on production

- [ ] Ten wrong passwords for one email → the next attempt is refused
      ("Request was throttled").
- [ ] Two parent accounts from different families: neither appears in the
      other's "New message" list, and neither can open a conversation with
      the other.
- [ ] A password reset signs the account out on another device.
- [ ] An invite email and a password-reset email arrive, from your domain,
      not in spam, and their links open the live site.
- [ ] Generating an AI comment works, or answers "busy, try again" rather
      than hanging.

## People and paperwork

- [ ] Gemini on a paid tier with no training on prompts; data-processing
      terms accepted (H-8).
- [ ] Data-processing agreement signed with the pilot school (H-8).
- [ ] Privacy notice published, including the AI data flow
      ([AI_DATA_FLOW.md](AI_DATA_FLOW.md)).
- [ ] Staff told not to put pupils' names in AI announcement briefs.
- [ ] Uptime monitor and Sentry alerts reach a phone (H-10).
- [ ] A named backup person has access to GitHub, Render, Neon, Vercel and
      Sentry.
- [ ] The runbook's contacts table is filled in ([RUNBOOK.md](RUNBOOK.md)).
- [ ] The pilot school knows the support hours and how to report a problem.
