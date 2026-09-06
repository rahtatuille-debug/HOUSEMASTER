"""
Tests for the accounts app: HasSchoolProfile permission, /api/me/, and the
SchoolViewSet itself (School is the one model that IS the tenant, rather
than reaching it via school_lookup).

This module also defines SchoolScopedAPITestCase, a shared base class used
by every other app's test suite (students, gradebook, attendance,
reporting). It exists here — rather than in a separate, non-test-ish file —
so Django's test discovery picks it up naturally and every app can just
`from accounts.tests import SchoolScopedAPITestCase` without an extra
import path to remember.

Run the whole suite with:
    python manage.py test

Run just this file with:
    python manage.py test accounts
"""
from django.contrib.auth.models import User
from django.core import mail
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from students.models import School
from .models import PasswordResetToken, Profile


class SchoolScopedAPITestCase(APITestCase):
    """
    Sets up two separate schools, each with one authenticated staff user,
    so every scoping test can assert that School A's client can see/act on
    School A's data and never School B's — and vice versa.

    Subclasses can add their own setUp() but MUST call
    super().setUp() first to get self.school_a / self.school_b /
    self.user_a / self.user_b / self.client_a / self.client_b.
    """

    def setUp(self):
        self.school_a = School.objects.create(name="Alpha Academy", report_tone="formal")
        self.school_b = School.objects.create(name="Beta College", report_tone="warm")

        self.user_a = User.objects.create_user(
            username="teacher_a", email="teacher.a@alpha.test", password="pass1234"
        )
        Profile.objects.create(user=self.user_a, school=self.school_a, role=Profile.Role.TEACHER)

        self.user_b = User.objects.create_user(
            username="teacher_b", email="teacher.b@beta.test", password="pass1234"
        )
        Profile.objects.create(user=self.user_b, school=self.school_b, role=Profile.Role.TEACHER)

        self.admin_a = User.objects.create_user(
            username="admin_a", email="admin.a@alpha.test", password="pass1234"
        )
        Profile.objects.create(user=self.admin_a, school=self.school_a, role=Profile.Role.ADMIN)

        self.client_a = self.authed_client(self.user_a)
        self.client_b = self.authed_client(self.user_b)

    @staticmethod
    def authed_client(user):
        from rest_framework.test import APIClient

        client = APIClient()
        token = RefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        return client


class HasSchoolProfilePermissionTests(SchoolScopedAPITestCase):
    def test_unauthenticated_request_is_401(self):
        from rest_framework.test import APIClient

        response = APIClient().get("/api/students/")
        self.assertEqual(response.status_code, 401)

    def test_authenticated_without_profile_is_403(self):
        from rest_framework.test import APIClient

        bare_user = User.objects.create_user(username="no_profile", password="pass1234")
        client = self.authed_client(bare_user)
        response = client.get("/api/students/")
        self.assertEqual(response.status_code, 403)

    def test_authenticated_with_profile_is_allowed(self):
        response = self.client_a.get("/api/students/")
        self.assertEqual(response.status_code, 200)


class MeEndpointTests(SchoolScopedAPITestCase):
    def test_me_returns_own_email_role_and_school(self):
        response = self.client_a.get("/api/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["email"], "teacher.a@alpha.test")
        self.assertEqual(response.data["role"], "teacher")
        self.assertEqual(response.data["school"]["id"], self.school_a.id)
        self.assertEqual(response.data["school"]["name"], "Alpha Academy")

    def test_me_never_leaks_other_schools_data(self):
        response = self.client_a.get("/api/me/")
        self.assertNotEqual(response.data["school"]["id"], self.school_b.id)


class SchoolViewSetScopingTests(SchoolScopedAPITestCase):
    """
    School is the one model that IS the tenant (school_lookup doesn't apply
    the normal way — see SchoolViewSet.get_queryset), so it gets its own
    explicit coverage rather than relying on the generic mixin tests below.
    """

    def test_list_only_returns_own_school(self):
        response = self.client_a.get("/api/schools/")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data]
        self.assertEqual(ids, [self.school_a.id])

    def test_cannot_retrieve_another_schools_row(self):
        response = self.client_a.get(f"/api/schools/{self.school_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_can_update_own_school(self):
        response = self.client_a.patch(
            f"/api/schools/{self.school_a.id}/", {"report_tone": "concise"}
        )
        self.assertEqual(response.status_code, 200)
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.report_tone, "concise")

    def test_cannot_update_another_schools_row(self):
        response = self.client_a.patch(
            f"/api/schools/{self.school_b.id}/", {"report_tone": "concise"}
        )
        self.assertEqual(response.status_code, 404)
        self.school_b.refresh_from_db()
        self.assertEqual(self.school_b.report_tone, "warm")

    def test_cannot_create_or_delete_schools_via_api(self):
        # SchoolViewSet.http_method_names excludes post/delete on purpose.
        response = self.client_a.post("/api/schools/", {"name": "New School"})
        self.assertEqual(response.status_code, 405)

        response = self.client_a.delete(f"/api/schools/{self.school_a.id}/")
        self.assertEqual(response.status_code, 405)


class PasswordResetTests(SchoolScopedAPITestCase):
    def test_request_with_known_email_sends_email_and_creates_token(self):
        response = self.client.post("/api/password-reset/", {"email": self.user_a.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetToken.objects.filter(user=self.user_a).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user_a.email, mail.outbox[0].to)

    def test_request_with_unknown_email_still_returns_200_and_sends_nothing(self):
        response = self.client.post("/api/password-reset/", {"email": "nobody@nowhere.test"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetToken.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_request_with_blank_email_is_a_validation_error(self):
        response = self.client.post("/api/password-reset/", {"email": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PasswordResetToken.objects.count(), 0)

    def test_request_matches_every_account_sharing_that_email(self):
        # User.email has no uniqueness constraint, so a shared address
        # should get a reset link for each account that uses it.
        self.user_b.email = self.user_a.email
        self.user_b.save(update_fields=["email"])
        response = self.client.post("/api/password-reset/", {"email": self.user_a.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetToken.objects.filter(user=self.user_a).count(), 1)
        self.assertEqual(PasswordResetToken.objects.filter(user=self.user_b).count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_confirm_with_valid_token_changes_password_and_consumes_token(self):
        reset_token = PasswordResetToken.objects.create(user=self.user_a)
        response = self.client.post(
            "/api/password-reset/confirm/",
            {"token": reset_token.token, "password": "a-brand-new-strong-pw9"},
        )
        self.assertEqual(response.status_code, 200)
        self.user_a.refresh_from_db()
        self.assertTrue(self.user_a.check_password("a-brand-new-strong-pw9"))
        reset_token.refresh_from_db()
        self.assertIsNotNone(reset_token.used_at)

    def test_confirm_rejects_reused_token(self):
        reset_token = PasswordResetToken.objects.create(user=self.user_a)
        self.client.post(
            "/api/password-reset/confirm/",
            {"token": reset_token.token, "password": "a-brand-new-strong-pw9"},
        )
        response = self.client.post(
            "/api/password-reset/confirm/",
            {"token": reset_token.token, "password": "another-strong-pw123"},
        )
        self.assertEqual(response.status_code, 400)

    def test_confirm_rejects_unknown_token(self):
        response = self.client.post(
            "/api/password-reset/confirm/",
            {"token": "not-a-real-token", "password": "a-brand-new-strong-pw9"},
        )
        self.assertEqual(response.status_code, 400)


class LoginTests(SchoolScopedAPITestCase):
    def test_login_with_email_and_password_succeeds(self):
        response = self.client.post(
            "/api/token/", {"email": self.user_a.email, "password": "pass1234"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(
            "/api/token/", {"email": self.user_a.email, "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 401)

    def test_login_with_username_field_instead_of_email_fails(self):
        # `username` is no longer accepted by this endpoint at all — only
        # `email` is a recognised field now.
        response = self.client.post(
            "/api/token/", {"username": self.user_a.username, "password": "pass1234"}
        )
        self.assertEqual(response.status_code, 400)

    def test_login_is_case_insensitive_on_email(self):
        response = self.client.post(
            "/api/token/", {"email": self.user_a.email.upper(), "password": "pass1234"}
        )
        self.assertEqual(response.status_code, 200)


class AcceptInviteTests(SchoolScopedAPITestCase):
    def _create_invite(self, email="new.teacher@alpha.test"):
        from .models import Invite

        return Invite.objects.create(
            school=self.school_a,
            role=Profile.Role.TEACHER,
            email=email,
            invited_by=self.admin_a,
        )

    def test_accept_with_valid_token_creates_account_with_invites_email(self):
        invite = self._create_invite()
        response = self.client.post(
            "/api/invites/accept/", {"token": invite.token, "password": "a-strong-new-pw9"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("access", response.data)

        user = User.objects.get(email="new.teacher@alpha.test")
        self.assertTrue(user.check_password("a-strong-new-pw9"))
        self.assertEqual(user.profile.school, self.school_a)
        self.assertEqual(user.profile.role, Profile.Role.TEACHER)

        invite.refresh_from_db()
        self.assertTrue(invite.is_accepted)
        self.assertEqual(invite.accepted_by, user)

    def test_accept_does_not_let_invitee_choose_a_different_email(self):
        # There's no `email`/`username` field on this endpoint at all —
        # the account's email always comes from the invite itself.
        invite = self._create_invite()
        response = self.client.post(
            "/api/invites/accept/",
            {"token": invite.token, "email": "someone-else@alpha.test", "password": "a-strong-new-pw9"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(email="new.teacher@alpha.test").exists())
        self.assertFalse(User.objects.filter(email="someone-else@alpha.test").exists())

    def test_accept_rejects_reused_token(self):
        invite = self._create_invite()
        self.client.post("/api/invites/accept/", {"token": invite.token, "password": "a-strong-new-pw9"})
        response = self.client.post(
            "/api/invites/accept/", {"token": invite.token, "password": "another-strong-pw2"}
        )
        self.assertEqual(response.status_code, 400)

    def test_accept_rejects_email_already_in_use(self):
        invite = self._create_invite(email=self.user_a.email)
        response = self.client.post(
            "/api/invites/accept/", {"token": invite.token, "password": "a-strong-new-pw9"}
        )
        self.assertEqual(response.status_code, 400)
