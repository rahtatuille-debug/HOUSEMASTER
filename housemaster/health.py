"""
GET/HEAD /healthz, for Render's health check and an uptime monitor (B-6).

Answered by the first middleware, before the host check (Render's probe
doesn't use a host in DJANGO_ALLOWED_HOSTS), the HTTPS redirect,
authentication and rate limits. It says only whether the database answers
and which commit is running, so the owner can check what is live:

    {"status": "ok", "commit": "8e9ad30"}      200
    {"status": "degraded"}                     503  (database not answering)

Nothing else is exposed: no versions, settings, counts or error details.
"""
import json
import logging
import os
import re

from django.db import connection, transaction
from django.http import HttpResponse

logger = logging.getLogger("housemaster.health")

PATH = "/healthz"
# Postgres gives up on the check after this long. (SQLite answers at once.)
STATEMENT_TIMEOUT_MS = 2000


def running_commit():
    commit = os.environ.get("RENDER_GIT_COMMIT", "").strip().lower()
    return commit[:7] if re.fullmatch(r"[0-9a-f]{7,40}", commit) else "unknown"


def database_answers():
    with transaction.atomic(), connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
        cursor.execute("SELECT 1")
        cursor.fetchone()


def _json(status, body):
    response = HttpResponse(json.dumps(body), status=status, content_type="application/json")
    response["Cache-Control"] = "no-store"
    return response


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != PATH or request.method not in ("GET", "HEAD"):
            return self.get_response(request)
        try:
            database_answers()
        except Exception:
            # The reason goes to the log (and Sentry), never into the answer.
            logger.exception("Health check: the database did not answer")
            response = _json(503, {"status": "degraded"})
        else:
            response = _json(200, {"status": "ok", "commit": running_commit()})
        if request.method == "HEAD":
            response.content = b""
        return response
