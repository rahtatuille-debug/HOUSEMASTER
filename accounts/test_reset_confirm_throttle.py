"""
B-3: password-reset confirmation has its own per-IP limit.

It used to share the invite bucket (invite previews and acceptance, parent
invites, class sign-up links), so a burst of parents joining from a
school's shared address could hold up someone's password reset from that
address, and a flurry of reset attempts could hold up the joining parents.
"""
from unittest.mock import patch

from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from .tests import SchoolScopedAPITestCase


def small(**rates):
    return patch.dict(api_settings.DEFAULT_THROTTLE_RATES, rates)


class ResetConfirmThrottleTests(SchoolScopedAPITestCase):
    def confirm(self, token="guess"):
        return APIClient().post("/api/password-reset/confirm/", {"token": token, "password": "A-long-password-9"},
                                format="json")

    def join(self, n=0):
        return APIClient().get(f"/api/join/guess{n}/")

    def test_a_burst_of_joining_parents_does_not_block_a_reset(self):
        with small(invite_ip="3/hour", password_reset_confirm_ip="3/hour"):
            self.assertEqual([self.join(i).status_code for i in range(4)][-1], 429)
            self.client.post("/api/password-reset/", {"email": self.user_a.email}, format="json")
            token = self.user_a.password_reset_tokens.get().token
            self.assertEqual(self.confirm(token).status_code, 200)

    def test_reset_attempts_do_not_block_joining_parents(self):
        with small(invite_ip="3/hour", password_reset_confirm_ip="3/hour"):
            self.assertEqual([self.confirm().status_code for _ in range(4)], [400, 400, 400, 429])
            self.assertEqual(self.join().status_code, 404)
            self.assertEqual(APIClient().get("/api/invites/preview/guess/").status_code, 404)

    def test_each_bucket_still_has_its_limit(self):
        with small(invite_ip="2/hour", password_reset_confirm_ip="2/hour"):
            self.assertEqual([self.confirm().status_code for _ in range(3)][-1], 429)
            self.assertEqual([self.join(i).status_code for i in range(3)][-1], 429)

    def test_rate_can_be_changed_by_environment(self):
        import os
        import subprocess
        import sys

        from django.conf import settings

        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        env.update({"HOUSEMASTER_SKIP_DOTENV": "1", "DJANGO_DEBUG": "True", "PASSWORD_RESET_CONFIRM_IP_RATE": "7/hour"})
        out = subprocess.run([sys.executable, "-c", "import housemaster.settings as s; "
                              "print(s.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['password_reset_confirm_ip'])"],
                             cwd=settings.BASE_DIR, env=env, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "7/hour", out.stderr)
