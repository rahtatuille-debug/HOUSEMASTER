"""
F-07: a slow or failing AI provider must never hang the app or turn into
a 500. Every call has a timeout (and a hard deadline behind it), provider
and network errors become a friendly 503, nothing is half-saved, and the
model name comes from GEMINI_MODEL.

These tests replace google.genai.Client, so nothing reaches the network.
"""
import json
import os
import time
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from google.genai import errors

from gradebook.models import Grade, Subject, Term
from reporting import ai
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

from accounts.tests import SchoolScopedAPITestCase

BUSY = "The writing assistant is busy, please try again in a minute."


def provider_error(cls, code, message="provider says no", status="X"):
    response = requests.Response()
    response.status_code = code
    response._content = json.dumps({"error": {"code": code, "message": message, "status": status}}).encode()
    return cls(code, response)


def fake_client(side_effect=None, text="SUMMARY:\nGood progress.\nCOMMENT:\nWell done this term."):
    """A stand-in for genai.Client that records how it was built and called."""
    client = MagicMock()
    if side_effect is not None:
        client.models.generate_content.side_effect = side_effect
    else:
        client.models.generate_content.return_value = MagicMock(text=text)
    factory = MagicMock(return_value=client)
    return factory, client


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-not-real"})
class AIFailureTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.make_admin(self.user_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        school_class = SchoolClass.objects.create(year_group=year, name="7A")
        self.student = Student.objects.create(school=self.school_a, first_name="Amina", last_name="Otieno",
                                              school_class=school_class)
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        maths = Subject.objects.create(school=self.school_a, name="Maths")
        Grade.objects.create(student=self.student, subject=maths, term=self.term, score=72, max_score=100)

    def generate(self):
        return self.client_a.post("/api/reports/generate/", {"student": self.student.id, "term": self.term.id},
                                  format="json")

    def assert_clean_busy(self, response):
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["detail"], BUSY)
        self.assertFalse(StudentReport.objects.exists(), "nothing may be saved when the provider fails")

    def test_timeout_becomes_a_503(self):
        factory, _ = fake_client(side_effect=requests.exceptions.ReadTimeout("slow"))
        with patch("google.genai.Client", factory):
            self.assert_clean_busy(self.generate())

    def test_connection_error_becomes_a_503(self):
        factory, _ = fake_client(side_effect=requests.exceptions.ConnectionError("network down"))
        with patch("google.genai.Client", factory):
            self.assert_clean_busy(self.generate())

    def assert_clean_503(self, response, words):
        self.assertEqual(response.status_code, 503)
        self.assertIn(words, response.data["detail"])
        self.assertNotEqual(response.data["detail"], BUSY)
        self.assertFalse(StudentReport.objects.exists())

    def test_rate_limited_provider_says_the_limit_was_reached(self):
        factory, _ = fake_client(side_effect=provider_error(errors.ClientError, 429, status="RESOURCE_EXHAUSTED"))
        with patch("google.genai.Client", factory), self.assertLogs("reporting.ai", "WARNING") as logs:
            self.assert_clean_503(self.generate(), "usage limit")
        self.assertIn("429", logs.output[0])

    def test_refused_key_says_so_not_busy(self):
        """A wrong or revoked GEMINI_API_KEY is a setup problem; "try again in a minute" would never work."""
        for code, message, status in [(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT"),
                                      (403, "Permission denied", "PERMISSION_DENIED"), (401, "Unauthenticated", "UNAUTHENTICATED")]:
            with self.subTest(code=code):
                factory, _ = fake_client(side_effect=provider_error(errors.ClientError, code, message, status))
                with patch("google.genai.Client", factory), self.assertLogs("reporting.ai", "WARNING") as logs:
                    self.assert_clean_503(self.generate(), "GEMINI_API_KEY")
                self.assertIn(str(code), logs.output[0])

    def test_unknown_model_says_so_not_busy(self):
        factory, _ = fake_client(side_effect=provider_error(errors.ClientError, 404, "models/x is not found", "NOT_FOUND"))
        with patch("google.genai.Client", factory):
            self.assert_clean_503(self.generate(), "GEMINI_MODEL")

    def test_the_log_never_holds_the_prompt_or_the_key(self):
        factory, _ = fake_client(side_effect=provider_error(errors.ClientError, 429, "quota for key test-key-not-real"))
        with patch("google.genai.Client", factory), self.assertLogs("reporting.ai", "WARNING") as logs:
            self.generate()
        text = "\n".join(logs.output)
        self.assertNotIn("Amina", text)
        self.assertNotIn("test-key-not-real", text)

    def test_provider_server_error_becomes_a_503(self):
        factory, _ = fake_client(side_effect=provider_error(errors.ServerError, 500))
        with patch("google.genai.Client", factory):
            self.assert_clean_busy(self.generate())

    def test_unexpected_errors_are_not_swallowed(self):
        # Programming errors must still reach Sentry as a 500.
        factory, _ = fake_client(side_effect=KeyError("bug"))
        with patch("google.genai.Client", factory), self.assertRaises(KeyError):
            self.generate()

    def test_failed_calls_still_count_towards_the_limit(self):
        factory, _ = fake_client(side_effect=requests.exceptions.ConnectionError("down"))
        with patch.dict(ai_rates(), {"ai_report_generation": "2/hour"}), patch("google.genai.Client", factory):
            codes = [self.generate().status_code for _ in range(3)]
        self.assertEqual(codes, [503, 503, 429])

    def test_every_call_has_a_timeout_and_uses_the_configured_model(self):
        factory, client = fake_client()
        with patch("google.genai.Client", factory), patch.dict(os.environ, {"GEMINI_MODEL": "some-model-001"}):
            self.assertEqual(self.generate().status_code, 200)
        http_options = factory.call_args.kwargs["http_options"]
        self.assertEqual(http_options.timeout, ai.timeout_seconds() * 1000)
        self.assertEqual(client.models.generate_content.call_args.kwargs["model"], "some-model-001")

    def test_hard_deadline_stops_a_call_that_ignores_the_timeout(self):
        def hang(**kwargs):
            time.sleep(3)

        factory, _ = fake_client(side_effect=hang)
        with patch("google.genai.Client", factory), patch.object(ai, "hard_deadline_seconds", return_value=0.5):
            started = time.monotonic()
            response = self.generate()
            elapsed = time.monotonic() - started
        self.assert_clean_busy(response)
        self.assertLess(elapsed, 2.5)

    def test_default_model_is_the_fast_stable_one(self):
        factory, client = fake_client()
        with patch("google.genai.Client", factory), patch.dict(os.environ, {"GEMINI_MODEL": ""}):
            self.assertEqual(self.generate().status_code, 200)
        self.assertEqual(client.models.generate_content.call_args.kwargs["model"], "gemini-3.5-flash-lite")

    def test_a_timeout_is_logged(self):
        def hang(**kwargs):
            time.sleep(2)

        factory, _ = fake_client(side_effect=hang)
        with patch("google.genai.Client", factory), patch.object(ai, "hard_deadline_seconds", return_value=0.3), \
                self.assertLogs("reporting.ai", "WARNING") as logs:
            self.assert_clean_busy(self.generate())
        self.assertIn("took too long", logs.output[0])

    def test_missing_key_is_still_a_503_with_its_own_message(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            response = self.generate()
        self.assertEqual(response.status_code, 503)
        self.assertIn("GEMINI_API_KEY", response.data["detail"])

    def test_class_run_step_also_returns_a_clean_503(self):
        start = self.client_a.post("/api/reports/generate-class/",
                                   {"school_class": self.student.school_class_id, "term": self.term.id},
                                   format="json")
        self.assertEqual(start.status_code, 200, start.data)
        factory, _ = fake_client(side_effect=requests.exceptions.ReadTimeout("slow"))
        with patch("google.genai.Client", factory):
            response = self.client_a.post("/api/reports/generate-class/next/",
                                          {"run": start.data["run"], "student": self.student.id}, format="json")
        self.assert_clean_busy(response)

    def test_announcement_drafting_explains_a_refused_key(self):
        factory, _ = fake_client(side_effect=provider_error(errors.ClientError, 400, "API key not valid.", "INVALID_ARGUMENT"))
        with patch("google.genai.Client", factory):
            response = self.client_a.post("/api/announcements/generate-text/",
                                          {"summary": "Sports day moved to Friday", "audience": "all_parents"},
                                          format="json")
        self.assertEqual(response.status_code, 503)
        self.assertIn("GEMINI_API_KEY", response.data["detail"])

    def test_announcement_drafting_returns_a_clean_503(self):
        factory, _ = fake_client(side_effect=provider_error(errors.ServerError, 503))
        with patch("google.genai.Client", factory):
            response = self.client_a.post("/api/announcements/generate-text/",
                                          {"summary": "Sports day moved to Friday", "audience": "all_parents"},
                                          format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["detail"], BUSY)


def ai_rates():
    from rest_framework.settings import api_settings

    return api_settings.DEFAULT_THROTTLE_RATES
