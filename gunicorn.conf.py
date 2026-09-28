"""
Gunicorn settings. Gunicorn reads this file from the working directory
automatically, so the Render start command should be just
`gunicorn housemaster.wsgi` with no flags that override it
(docs/HUMAN_ACTIONS.md, H-4).

Threads, not extra processes: each process imports Django, Sentry and the
AI SDK, and the free tier has 512 MB. With threads, one slow AI call ties up
one thread instead of the whole app.
"""
import os

worker_class = "gthread"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
# Longer than the AI provider's hard deadline (GEMINI_TIMEOUT_SECONDS + 5),
# so a slow AI call gets a clean 503 rather than a killed worker.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
