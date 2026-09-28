"""
F-18: a broken email setup can't stay silent, and reset or invite links
never end up in the server log.

- In production with no email service configured, messages are dropped
  with an ERROR log (which Sentry records) naming the subject only; the
  link is never printed.
- A failed send logs an ERROR without the link and never turns into a 500
  (which, on the reset form, would reveal that the account exists).
"""
import io
import os
import smtplib
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import Invite, PasswordResetToken

from .tests import SchoolScopedAPITestCase

UNDELIVERED = "housemaster.mail.UndeliveredEmailBackend"
BASE_DIR = Path(__file__).resolve().parent.parent


class EmailFailureTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_production_without_an_email_service_drops_mail_instead_of_printing_links(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "EMAIL_"))}
        env.update({"HOUSEMASTER_SKIP_DOTENV": "1", "DJANGO_DEBUG": "False", "SECRET_KEY": "k" * 60,
                    "DATABASE_URL": "postgresql://u:p@db.example.org/x", "DJANGO_ALLOWED_HOSTS": "api.example.org",
                    "CORS_ALLOWED_ORIGINS": "https://app.example.org"})
        code = "import housemaster.settings as s; print(s.EMAIL_BACKEND)"
        result = subprocess.run([sys.executable, "-c", code], cwd=BASE_DIR, env=env, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), UNDELIVERED, result.stderr)

    @override_settings(EMAIL_BACKEND=UNDELIVERED)
    def test_undelivered_reset_logs_an_error_without_the_link(self):
        out = io.StringIO()
        with self.assertLogs("housemaster.mail", level="ERROR") as logs, redirect_stdout(out):
            response = APIClient().post("/api/password-reset/", {"email": self.user_a.email}, format="json")
        self.assertEqual(response.status_code, 200)
        token = PasswordResetToken.objects.get(user=self.user_a).token
        self.assertNotIn(token, "\n".join(logs.output) + out.getvalue())
        self.assertIn("Reset your HouseMaster password", "\n".join(logs.output))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    def test_smtp_failure_on_reset_is_logged_and_the_answer_stays_the_same(self):
        with patch("django.core.mail.backends.smtp.EmailBackend.send_messages",
                   side_effect=smtplib.SMTPException("server said no")), \
                self.assertLogs("accounts.emails", level="ERROR") as logs:
            real = APIClient().post("/api/password-reset/", {"email": self.user_a.email}, format="json")
        unknown = APIClient().post("/api/password-reset/", {"email": "ghost@example.org"}, format="json")
        self.assertEqual((real.status_code, unknown.status_code), (200, 200))
        self.assertEqual(real.data, unknown.data)
        token = PasswordResetToken.objects.get(user=self.user_a).token
        self.assertNotIn(token, "\n".join(logs.output))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    def test_invite_send_failure_is_logged_without_the_link(self):
        admin = self.authed_client(self.admin_a)
        with patch("django.core.mail.backends.smtp.EmailBackend.send_messages",
                   side_effect=smtplib.SMTPException("server said no")), \
                patch("django.core.mail.backends.smtp.EmailBackend.open", return_value=True), \
                self.assertLogs(level="ERROR") as logs, self.captureOnCommitCallbacks(execute=True):
            response = admin.post("/api/invites/", {"name": "New Person", "email": "new@example.org",
                                                    "role": "teacher"}, format="json")
        self.assertEqual(response.status_code, 201)
        token = Invite.objects.get(email="new@example.org").token
        self.assertNotIn(token, "\n".join(logs.output))

    @override_settings(EMAIL_BACKEND=UNDELIVERED)
    def test_admin_is_told_when_a_reset_they_sent_was_not_delivered(self):
        admin = self.authed_client(self.admin_a)
        with self.assertLogs("housemaster.mail", level="ERROR"):
            response = admin.post(f"/api/staff/{self.user_a.profile.id}/send-password-reset/")
        self.assertEqual(response.status_code, 503)
