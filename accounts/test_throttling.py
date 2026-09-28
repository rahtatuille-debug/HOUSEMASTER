"""
F-05: brute-force and mail-bombing limits on the public endpoints.

Each sensitive endpoint is limited twice: per client IP address and per
email address taken from the request body. The per-email limit doesn't
depend on the IP at all, so a spoofed X-Forwarded-For header can't get
round it. Rates are patched small here (DRF binds THROTTLE_RATES onto the
class, so override_settings can't change them).
"""
import re
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework.settings import api_settings
from rest_framework.test import APIClient


from .tests import SchoolScopedAPITestCase

PASSWORD = "Correct-Horse-9"
RATES = api_settings.DEFAULT_THROTTLE_RATES


def small(**rates):
    return patch.dict(RATES, rates)


def without_seconds(response):
    return re.sub(r"\d+", "N", str(response.json()))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ThrottleTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.user_a.set_password(PASSWORD)
        self.user_a.save()

    def login(self, email, password, ip="198.51.100.1"):
        return APIClient().post("/api/token/", {"email": email, "password": password}, format="json",
                                HTTP_X_FORWARDED_FOR=ip)

    # --- login ---------------------------------------------------------

    def test_failed_logins_per_email_are_limited_even_when_the_ip_rotates(self):
        with small(login_email="3/hour", login_ip="100/hour"):
            codes = [self.login(self.user_a.email, "wrong", ip=f"10.0.0.{i}").status_code for i in range(3)]
            self.assertEqual(codes, [401, 401, 401])
            blocked = self.login(self.user_a.email, PASSWORD, ip="10.9.9.9")
            self.assertEqual(blocked.status_code, 429)
            self.assertIn("Retry-After", blocked)

    def test_failed_logins_per_ip_are_limited(self):
        with small(login_email="100/hour", login_ip="3/hour"):
            for i in range(3):
                self.assertEqual(self.login(f"nobody{i}@example.org", "wrong").status_code, 401)
            self.assertEqual(self.login("someone.else@example.org", "wrong").status_code, 429)

    def test_successful_logins_are_not_counted(self):
        with small(login_email="2/hour", login_ip="2/hour"):
            for _ in range(5):
                self.assertEqual(self.login(self.user_a.email, PASSWORD).status_code, 200)

    def test_throttled_answer_is_the_same_for_real_and_unknown_accounts(self):
        with small(login_email="1/hour", login_ip="100/hour"):
            self.login(self.user_a.email, "wrong")
            self.login("ghost@example.org", "wrong")
            real = self.login(self.user_a.email, "wrong")
            ghost = self.login("ghost@example.org", "wrong")
        self.assertEqual((real.status_code, ghost.status_code), (429, 429))
        self.assertEqual(without_seconds(real), without_seconds(ghost))

    def test_one_throttled_email_does_not_block_another_user(self):
        self.admin_a.set_password(PASSWORD)
        self.admin_a.save()
        with small(login_email="1/hour", login_ip="100/hour"):
            self.login(self.user_a.email, "wrong")
            self.assertEqual(self.login(self.user_a.email, PASSWORD).status_code, 429)
            self.assertEqual(self.login(self.admin_a.email, PASSWORD).status_code, 200)

    def test_email_is_normalised_for_the_limit(self):
        with small(login_email="2/hour", login_ip="100/hour"):
            self.login(self.user_a.email.upper(), "wrong")
            self.login(f"  {self.user_a.email}  ", "wrong")
            self.assertEqual(self.login(self.user_a.email, "wrong").status_code, 429)

    def test_unrelated_endpoints_are_unaffected(self):
        access = self.login(self.user_a.email, PASSWORD).data["access"]
        with small(login_email="1/hour", login_ip="1/hour"):
            self.login(self.user_a.email, "wrong")
            self.assertEqual(self.login(self.user_a.email, "wrong").status_code, 429)
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
            self.assertEqual(client.get("/api/me/").status_code, 200)

    def test_spoofed_forwarded_for_is_ignored_once_the_proxy_count_is_set(self):
        with small(login_email="100/hour", login_ip="3/hour"), \
                override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}):
            for i in range(3):
                self.login(f"a{i}@example.org", "wrong", ip=f"10.0.0.{i}, 203.0.113.7")
            # The attacker controls the first entries; the proxy appends the real address last.
            self.assertEqual(self.login("b@example.org", "wrong", ip="10.1.1.1, 203.0.113.7").status_code, 429)

    # --- password reset --------------------------------------------------

    def reset(self, email, ip="198.51.100.1"):
        return APIClient().post("/api/password-reset/", {"email": email}, format="json", HTTP_X_FORWARDED_FOR=ip)

    def test_reset_requests_per_email_are_limited_and_stop_the_mail_bomb(self):
        with small(password_reset_email="3/hour", password_reset_ip="100/hour"):
            codes = [self.reset(self.user_a.email, ip=f"10.0.0.{i}").status_code for i in range(6)]
        self.assertEqual(codes, [200, 200, 200, 429, 429, 429])
        self.assertEqual(len(mail.outbox), 3)

    def test_reset_requests_per_ip_are_limited(self):
        with small(password_reset_email="100/hour", password_reset_ip="2/hour"):
            codes = [self.reset(f"x{i}@example.org").status_code for i in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_reset_throttle_answer_is_uniform(self):
        with small(password_reset_email="1/hour", password_reset_ip="100/hour"):
            self.reset(self.user_a.email)
            self.reset("ghost@example.org")
            real, ghost = self.reset(self.user_a.email), self.reset("ghost@example.org")
        self.assertEqual(without_seconds(real), without_seconds(ghost))

    # --- invites, sign-up links, registration, refresh --------------------

    def test_invite_preview_and_accept_are_limited_per_ip(self):
        with small(invite_ip="3/hour"):
            codes = [APIClient().get(f"/api/invites/preview/guess{i}/").status_code for i in range(3)]
            self.assertEqual(codes, [404, 404, 404])
            self.assertEqual(APIClient().post("/api/invites/accept/", {"token": "guess"}, format="json").status_code,
                             429)
            self.assertEqual(APIClient().get("/api/guardian-invites/preview/guess/").status_code, 429)

    def test_join_link_is_limited_per_ip(self):
        with small(invite_ip="2/hour"):
            codes = [APIClient().get(f"/api/join/guess{i}/").status_code for i in range(3)]
        self.assertEqual(codes[-1], 429)

    def test_registration_per_email_is_limited_even_when_the_ip_rotates(self):
        body = {"school_name": "Gamma School", "name": "Some One", "password": "Long-Enough-Pass-1",
                "accept_privacy": True}
        with small(school_registration="100/hour", school_registration_email="2/day"):
            codes = [APIClient().post("/api/schools/register/", {**body, "email": "target@example.org"},
                                      format="json", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code
                     for i in range(3)]
        # The second attempt is refused as a duplicate account; the third is throttled.
        self.assertEqual(codes[0], 201)
        self.assertEqual(codes[2], 429)

    def test_token_refresh_is_limited_per_ip(self):
        with small(token_refresh_ip="2/hour"):
            codes = [APIClient().post("/api/token/refresh/", {"refresh": "x"}, format="json").status_code
                     for _ in range(3)]
        self.assertEqual(codes, [401, 401, 429])

    # --- password policy -------------------------------------------------

    def test_passwords_need_at_least_ten_characters(self):
        body = {"school_name": "Delta School", "name": "Some One", "email": "delta@example.org",
                "accept_privacy": True}
        short = APIClient().post("/api/schools/register/", {**body, "password": "Nine-char"}, format="json")
        self.assertEqual(short.status_code, 400)
        self.assertIn("password", short.data)
        common = APIClient().post("/api/schools/register/", {**body, "password": "password1234"}, format="json")
        self.assertEqual(common.status_code, 400)
        ok = APIClient().post("/api/schools/register/", {**body, "password": "Ten-chars!"}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
