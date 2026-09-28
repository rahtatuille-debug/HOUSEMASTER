"""
F-04: a password change or reset ends every existing session, refresh
tokens rotate and can't be replayed, and logging out kills the refresh
token that was used.
"""
import base64
import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import PasswordResetToken, UserSecurity

from .tests import SchoolScopedAPITestCase

PASSWORD = "Correct-Horse-9"


class TokenRevocationTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.user_a.set_password(PASSWORD)
        self.user_a.save()

    def login(self):
        response = APIClient().post("/api/token/", {"email": self.user_a.email, "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    @staticmethod
    def me(access):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return client.get("/api/me/")

    @staticmethod
    def refresh(token):
        return APIClient().post("/api/token/refresh/", {"refresh": token}, format="json")

    def test_login_still_works_and_tokens_carry_a_version(self):
        tokens = self.login()
        self.assertEqual(self.me(tokens["access"]).status_code, 200)
        self.assertIn("tv", RefreshToken(tokens["refresh"]).payload)

    def test_password_change_ends_existing_sessions(self):
        tokens = self.login()
        self.user_a.set_password("Another-Horse-10")
        self.user_a.save()
        self.assertEqual(self.me(tokens["access"]).status_code, 401)
        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)

    def test_password_reset_ends_existing_sessions(self):
        tokens = self.login()
        reset = PasswordResetToken.objects.create(user=self.user_a)
        response = APIClient().post("/api/password-reset/confirm/",
                                    {"token": reset.token, "password": "Reset-Horse-11"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.me(tokens["access"]).status_code, 401)
        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)

    def test_new_login_after_password_change_works(self):
        self.user_a.set_password("Another-Horse-10")
        self.user_a.save()
        response = APIClient().post("/api/token/", {"email": self.user_a.email, "password": "Another-Horse-10"},
                                    format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.me(response.data["access"]).status_code, 200)

    def test_refresh_rotates_and_the_old_refresh_token_cannot_be_replayed(self):
        tokens = self.login()
        first = self.refresh(tokens["refresh"])
        self.assertEqual(first.status_code, 200)
        self.assertIn("refresh", first.data)
        self.assertNotEqual(first.data["refresh"], tokens["refresh"])
        self.assertEqual(self.me(first.data["access"]).status_code, 200)
        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)
        self.assertEqual(self.refresh(first.data["refresh"]).status_code, 200)

    def test_logout_blacklists_the_refresh_token_and_is_idempotent(self):
        tokens = self.login()
        response = APIClient().post("/api/logout/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)
        again = APIClient().post("/api/logout/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(again.status_code, 200)
        garbage = APIClient().post("/api/logout/", {"refresh": "not-a-token"}, format="json")
        self.assertEqual(garbage.status_code, 200)

    def test_logout_needs_a_refresh_token(self):
        self.assertEqual(APIClient().post("/api/logout/", {}, format="json").status_code, 400)

    def test_deactivation_still_revokes(self):
        tokens = self.login()
        self.user_a.is_active = False
        self.user_a.save()
        self.assertEqual(self.me(tokens["access"]).status_code, 401)
        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)

    def test_reactivation_does_not_revive_old_tokens(self):
        tokens = self.login()
        self.user_a.is_active = False
        self.user_a.save()
        self.user_a.is_active = True
        self.user_a.save()
        self.assertEqual(self.me(tokens["access"]).status_code, 401)

    def test_token_without_version_claim_is_accepted_while_version_is_zero(self):
        # Tokens issued before this change have no claim; they must keep
        # working so the deploy doesn't sign everyone out.
        # setUp changed the password, so put the version back to where
        # every account starts after the migration.
        UserSecurity.objects.filter(user=self.user_a).update(token_version=0)
        legacy = RefreshToken.for_user(self.user_a)
        self.assertNotIn("tv", legacy.payload)
        self.assertEqual(self.me(str(legacy.access_token)).status_code, 200)

    def test_token_without_version_claim_is_rejected_once_version_moves(self):
        legacy = RefreshToken.for_user(self.user_a)
        self.user_a.set_password("Another-Horse-10")
        self.user_a.save()
        self.assertEqual(self.me(str(legacy.access_token)).status_code, 401)
        self.assertEqual(self.refresh(str(legacy)).status_code, 401)

    def test_tampered_and_unsigned_tokens_are_still_rejected(self):
        access = self.login()["access"]
        header, payload, signature = access.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        claims["user_id"] = str(self.admin_a.id)
        forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        self.assertEqual(self.me(f"{header}.{forged_payload}.{signature}").status_code, 401)
        none_header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
        self.assertEqual(self.me(f"{none_header}.{forged_payload}.").status_code, 401)

    def test_refresh_lifetime_defaults_to_three_days(self):
        self.assertEqual(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"], timedelta(days=3))
        self.assertEqual(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"], timedelta(hours=1))

    def test_invite_and_registration_tokens_carry_a_version(self):
        from accounts.tokens import tokens_for

        self.assertIn("tv", RefreshToken(tokens_for(User.objects.get(pk=self.user_a.pk))["refresh"]).payload)
