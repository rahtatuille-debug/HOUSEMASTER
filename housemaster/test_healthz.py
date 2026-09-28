"""
B-6: GET/HEAD /healthz for Render's health check and an uptime monitor.

It answers before any host check, HTTPS redirect, authentication or rate
limit, says only whether the database answers and which commit is running,
and leaves every other path exactly as it was.
"""
import json
from unittest.mock import patch

from django.conf import settings
from django.db.utils import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.settings import api_settings


class HealthzTests(TestCase):
    def get(self, path="/healthz", **extra):
        return self.client.get(path, **extra)

    def test_ok_with_a_database(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "commit": "unknown"})
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Content-Type"], "application/json")

    def test_commit_is_the_first_seven_characters_of_render_git_commit(self):
        with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "8e9ad30f1b2c3d4e5f60718293a4b5c6d7e8f901"}):
            self.assertEqual(self.get().json()["commit"], "8e9ad30")

    def test_commit_that_is_not_a_git_hash_is_not_echoed(self):
        with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "<script>alert(1)</script>"}):
            self.assertEqual(self.get().json()["commit"], "unknown")

    def test_degraded_when_the_database_is_down(self):
        with patch("housemaster.health.database_answers", side_effect=OperationalError("could not connect")):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "degraded"})

    def test_database_check_failure_detail_is_never_in_the_body(self):
        with patch("django.db.backends.utils.CursorWrapper.execute",
                   side_effect=OperationalError('password authentication failed for user "neondb_owner"')):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("neondb", response.content.decode())

    def test_head_answers_without_a_body(self):
        response = self.client.head("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    def test_unexpected_host_is_answered_but_other_paths_still_check_it(self):
        self.assertEqual(self.get(HTTP_HOST="10.201.3.7:10000").status_code, 200)
        self.assertEqual(self.client.get("/api/me/", HTTP_HOST="10.201.3.7:10000").status_code, 400)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_not_redirected_to_https(self):
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(self.client.get("/api/me/").status_code, 301)

    def test_body_holds_nothing_else(self):
        body = self.get().content.decode()
        self.assertEqual(set(json.loads(body)), {"status", "commit"})
        for secret in (settings.SECRET_KEY, str(settings.DATABASES["default"]["NAME"]), "Django", "Python"):
            self.assertNotIn(secret, body)

    def test_never_throttled(self):
        tiny = {scope: "1/hour" for scope in api_settings.DEFAULT_THROTTLE_RATES}
        with patch.dict(api_settings.DEFAULT_THROTTLE_RATES, tiny):
            codes = {self.get().status_code for _ in range(30)}
        self.assertEqual(codes, {200})

    def test_other_paths_and_methods_are_unchanged(self):
        self.assertEqual(self.client.post("/healthz").status_code, 404)
        self.assertEqual(self.get("/healthz/").status_code, 404)
        self.assertEqual(self.get("/healthzx").status_code, 404)
        self.assertEqual(self.client.get("/api/me/").status_code, 401)


class HealthzPlacementTests(SimpleTestCase):
    def test_health_check_runs_before_every_other_middleware(self):
        self.assertEqual(settings.MIDDLEWARE[0], "housemaster.health.HealthCheckMiddleware")
