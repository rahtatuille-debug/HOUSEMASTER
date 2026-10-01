# Environment variables

Everything the backend reads from its environment, what production should
use, and what happens when it is missing. Set these on Render: the backend
service → **Environment**. Frontend variables are set on Vercel (bottom of
this page).

"Refuses to start" means the settings raise `ImproperlyConfigured`: the
Render build (which runs `collectstatic`) fails and Render keeps the
previous version running. "Deploy check" means `manage.py check --deploy`
reports it (CI runs that with `--fail-level ERROR`).

## Required in production

| Variable | Production value | If missing or wrong |
|---|---|---|
| `DJANGO_DEBUG` | unset, or `False` | Unset means production mode. `True` turns on local-development mode; never set it on Render. |
| `SECRET_KEY` | 50+ random characters, unique to production. Generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"` | Refuses to start if missing, shorter than 50, or starting with `django-insecure`. Changing it signs everyone out. |
| `DATABASE_URL` | Neon's **pooled** connection string with `?sslmode=require` | Refuses to start. There is no SQLite fallback in production. |
| `DJANGO_ALLOWED_HOSTS` | The Render hostname, e.g. `housemaster-api.onrender.com`, plus any custom domain, comma-separated | Refuses to start if empty. |
| `CORS_ALLOWED_ORIGINS` | The exact Vercel production origin(s), e.g. `https://housemaster.vercel.app` | Refuses to start if empty or if it lists `*`, `localhost` or `127.0.0.1`. |
| `FRONTEND_URL` | The Vercel production origin (used in invite and password-reset links) | Deploy check error `housemaster.E001` if it isn't an https production address. |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` | Deploy check error `housemaster.E002`. Without it, production mail is dropped with an ERROR in the log and Sentry (never printed, so no link leaks), and nothing reaches anyone. |
| `EMAIL_HOST`, `EMAIL_PORT` (587), `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` (`true`) | Your SMTP provider's values | Invites and resets aren't delivered. |
| `DEFAULT_FROM_EMAIL` | An address on a domain you have verified with the SMTP provider | Default `noreply@housemaster.local` lands in spam. |
| `DRF_NUM_PROXIES` | The number of proxies in front of the app (measure it, see below; expected `1` on Render) | Deploy check warning `housemaster.W001`. Without it anyone can dodge the per-IP rate limits by sending their own `X-Forwarded-For` header. |

## Strongly recommended

| Variable | Value | Notes |
|---|---|---|
| `SENTRY_DSN` | From Sentry → Project → Client Keys | No error reports without it. |
| `SENTRY_ENVIRONMENT` | `production` | |
| `THROTTLE_CACHE` | `db` | Keeps rate-limit counters in the database, so they survive restarts (the free tier restarts whenever it sleeps). Needs `python manage.py createcachetable` in the build command. Default: in-memory. |
| `GEMINI_API_KEY` | A key on a paid, no-training Gemini tier (H-8) | Without it the AI buttons answer 503 "GEMINI_API_KEY is not set". |
| `WEB_CONCURRENCY` | `1` on the free tier (512 MB), `2` on Starter | Gunicorn processes (`gunicorn.conf.py`). |

## Optional tuning

| Variable | Default | What it does |
|---|---|---|
| `GUNICORN_THREADS` | `4` | Threads per process. One slow request only ties up one thread. |
| `GUNICORN_TIMEOUT` | `60` | Seconds before gunicorn gives up on a request. Keep it above `GEMINI_TIMEOUT_SECONDS + 5`. |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Model used for report comments and announcement drafts. |
| `GEMINI_TIMEOUT_SECONDS` | `20` | Per-call timeout; a hard deadline 5 s later backs it up. |
| `JWT_ACCESS_TOKEN_MINUTES` | `60` | Lifetime of an access token. |
| `JWT_REFRESH_TOKEN_DAYS` | `3` | Lifetime of a refresh token. Each refresh issues a new one, so active users stay signed in. |
| `LOGIN_EMAIL_RATE` / `LOGIN_IP_RATE` | `10/hour` / `30/hour` | Failed logins per email / per IP. Successful logins don't count. |
| `PASSWORD_RESET_EMAIL_RATE` / `PASSWORD_RESET_IP_RATE` | `5/hour` / `20/hour` | Reset requests. |
| `INVITE_IP_RATE` | `60/hour` | Invite and parent-invite preview/accept, class sign-up links. |
| `PASSWORD_RESET_CONFIRM_IP_RATE` | `60/hour` | Setting a new password from a reset link, per IP. Its own bucket, so parents joining from a shared school address don't hold up a reset. |
| `SCHOOL_REGISTRATION_RATE` / `SCHOOL_REGISTRATION_EMAIL_RATE` | `5/hour` / `3/day` | New school sign-ups per IP / per email. |
| `TOKEN_REFRESH_IP_RATE` | `600/hour` | Token refresh and logout per IP (high because mobile networks share addresses). |
| `INVITE_SEND_USER_RATE` / `INVITE_SEND_RECIPIENT_RATE` | `100/hour` / `5/day` | Invite emails (new or renewed) per admin / per recipient address across all schools. |
| `ALERT_SCHOOL_RATE` / `ALERT_TEST_SCHOOL_RATE` | `10/day` / `5/day` | Urgent alerts one school can send, and test alerts (their own budget, so testing never uses up a real emergency's). A refused or invalid alert doesn't count. |
| `CLASS_MESSAGE_RATE` | `30/hour` | Messages to a whole class, per sender. |
| `SECURE_HSTS_SECONDS` | `2592000` (30 days) | How long browsers must use HTTPS. Raise to `31536000` after a clean month. |
| `AI_REPORT_GENERATION_RATE`, `AI_CLASS_REPORT_GENERATION_RATE`, `AI_ANNOUNCEMENT_DRAFTING_RATE` | `30/hour`, `5/hour`, `30/hour` | Per-user AI limits. |
| `NOTIFICATIONS_IN_BACKGROUND` | `true` | Send parent notification emails on a background thread. |
| `LOG_CLIENT_IP_DEBUG` | unset | `1` logs the first 20 requests' `X-Forwarded-For` for measuring `DRF_NUM_PROXIES`. Turn it off afterwards: it logs IP addresses. |
| `DJANGO_ADMIN_PATH` | `admin/` | Where the Django admin lives. **Production: set something hard to guess**, e.g. `manage-7f3c2a/`. |
| `ADMIN_LOGIN_RATE` | `10` | Failed admin sign-ins per client address per hour. |
| `RETENTION_INACTIVE_STUDENT_YEARS` | unset (off) | Years after a student leaves before `manage.py apply_retention --apply` anonymises them. Counsel decides the period ([DESIGN_data_subject_tooling.md](DESIGN_data_subject_tooling.md)). |

## Set by Render (nothing to do)

| Variable | Used for |
|---|---|
| `RENDER_GIT_COMMIT` | `/healthz` reports its first 7 characters as `commit`, so you can see which commit is live. Anything that isn't a git hash is reported as `unknown`. |

`/healthz` answers before the host check and the HTTPS redirect, so Render's
health check works whatever host it uses; it needs no variable. Set
Render's **Health Check Path** to `/healthz` (HUMAN_ACTIONS.md, H-4).

## Per-school settings (not environment variables)

| Setting | Default | Where |
|---|---|---|
| School time zone (`School.timezone`) | `Africa/Nairobi` for every existing and new school | Admins change it in **Setup → School time zone** (or `PATCH /api/schools/<id>/` with `{"timezone": "Europe/London"}`). It decides when the school's day starts: "today" for registers, the dashboard, teacher home, ages on profiles, graduation dates and the date printed on report cards. Teachers can't change it. |

Django's own `TIME_ZONE` stays `Africa/Nairobi` and is only used where no
particular school is involved (for example `apply_retention`).

## Must stay unset in production

| Variable | Why |
|---|---|
| `DEMO_PASSWORD` | Creates demo schools with a shared password when `seed_demo_school` runs (also after every `migrate`). With `DJANGO_DEBUG` off the command now refuses and creates nothing unless `ALLOW_DEMO_SEED=1` is also set; it exits normally, so deploys don't fail. The large demo school (HouseMaster Demo College: about 1,000 students, five years of marks and report cards) is never built on deploy: run `python manage.py seed_large_demo` once on a demo server: in Render's Shell, or (without Shell) by adding ` && python manage.py seed_large_demo` to the end of the Build Command for one deploy. It takes a few minutes and adds about 300,000 rows; once the school exists it only prints "already exists". |
| `ALLOW_DEMO_SEED` | Set to `1` only on a server that exists purely for demos, never on one holding real schools. |
| `ALLOW_REMOTE_TEST_DB` | Lets the test suite create and drop databases on a remote server. |
| `HOUSEMASTER_SKIP_DOTENV` | Used only by the settings tests. |

`DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` and
`DJANGO_SUPERUSER_PASSWORD` are read by `manage.py sync_superuser`, which
creates the superuser if it doesn't exist and otherwise leaves it alone. To
recover a lost password on the free tier (no shell), set
`SYNC_SUPERUSER_RESET_PASSWORD=true` for **one** deploy: the password is reset
to `DJANGO_SUPERUSER_PASSWORD` and the deploy log says so loudly. Remove the
setting straight afterwards. Give the superuser a long random password from a
password manager.

## Finding `DRF_NUM_PROXIES`

The rate limits need the visitor's real IP address. Render's proxy adds it
to the end of the `X-Forwarded-For` header, but a visitor can put anything
they like at the start, so the app must know how many entries at the end
were added by proxies it trusts. Measure it rather than guessing:

1. On Render, set `LOG_CLIENT_IP_DEBUG=1` and save (Render redeploys).
2. Find your own public IP address (search "what is my IP" on the device).
3. Open the app from that device and sign in, then look at Render → **Logs**
   for lines like
   `X-Forwarded-For='41.90.x.x' REMOTE_ADDR=10.x.x.x identity=...`.
4. Count the addresses in `X-Forwarded-For` from the right up to and
   including yours. If yours is the only (or last) one, the value is `1`.
   If one more address follows yours (for example a CDN), it is `2`.
5. Set `DRF_NUM_PROXIES` to that number, **remove** `LOG_CLIENT_IP_DEBUG`,
   and save.
6. Check: repeat step 3 with `LOG_CLIENT_IP_DEBUG=1` briefly if you want to
   confirm `identity=` now shows your own address, then remove it again.

## Frontend (Vercel → Project → Settings → Environment Variables)

| Variable | Environments | Value |
|---|---|---|
| `VITE_API_BASE_URL` | Production (and Preview if previews are used) | The Render backend URL, e.g. `https://housemaster-api.onrender.com`. A production build fails without it. |
| `VITE_SENTRY_DSN` | Production, Preview | The frontend Sentry project's DSN. A production build warns without it. |
| `VITE_SENTRY_ENVIRONMENT` | Production: `production`; Preview: `preview` | |

## GitHub repository secrets (backups)

`BACKUP_DATABASE_URL`, `BACKUP_PASSPHRASE`, and optionally
`BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`,
`BACKUP_S3_REGION`, `BACKUP_S3_ENDPOINT`. See [BACKUPS.md](BACKUPS.md).
