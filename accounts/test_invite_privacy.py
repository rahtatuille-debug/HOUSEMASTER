"""
F-12: creating an invite must not tell one school's admin whether an email
has an account at another school, and invites can't be used to flood a
mailbox.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework.settings import api_settings

from accounts.models import Invite, Profile
from guardians.models import Guardian
from students.models import SchoolClass, Student, YearGroup

from .tests import SchoolScopedAPITestCase

VOLATILE = {"id", "token", "email", "name", "created_at", "expires_at", "invite_url", "invited_by_email"}


def shape(response):
    return {k: v for k, v in response.data.items() if k not in VOLATILE}


def rates(**values):
    return patch.dict(api_settings.DEFAULT_THROTTLE_RATES, values)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvitePrivacyTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.admin = self.authed_client(self.admin_a)
        # Someone with an account at school B only.
        self.b_parent = User.objects.create_user(username="b.parent", email="b.parent@example.org", password="x")
        Guardian.objects.create(user=self.b_parent, school=self.school_b, display_name="B Parent")
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.kid = Student.objects.create(school=self.school_a, first_name="Amina", last_name="Otieno",
                                          school_class=klass)

    def staff_invite(self, email, client=None):
        return (client or self.admin).post("/api/invites/", {"name": "New Person", "email": email, "role": "teacher"},
                                           format="json")

    def parent_invite(self, email, client=None):
        return (client or self.admin).post("/api/guardian-invites/",
                                           {"name": "New Parent", "email": email, "students": [self.kid.id]},
                                           format="json")

    def test_staff_invite_cannot_tell_other_school_accounts_from_unknown_emails(self):
        elsewhere = self.staff_invite("teacher.b@beta.test")
        unknown = self.staff_invite("nobody@example.org")
        self.assertEqual((elsewhere.status_code, unknown.status_code), (201, 201))
        self.assertEqual(shape(elsewhere), shape(unknown))

    def test_parent_invite_cannot_tell_other_school_accounts_from_unknown_emails(self):
        elsewhere = self.parent_invite("b.parent@example.org")
        unknown = self.parent_invite("nobody2@example.org")
        self.assertEqual((elsewhere.status_code, unknown.status_code), (201, 201))
        self.assertEqual(shape(elsewhere), shape(unknown))

    def test_accepting_an_invite_for_an_email_used_elsewhere_is_still_refused(self):
        self.staff_invite("teacher.b@beta.test")
        invite = Invite.objects.get(email="teacher.b@beta.test")
        response = self.client.post("/api/invites/accept/",
                                    {"token": invite.token, "password": "Long-Enough-Pass-1", "accept_privacy": True},
                                    format="json")
        self.assertEqual(response.status_code, 400)

    def test_same_school_duplicates_still_get_the_helpful_message(self):
        staff = self.staff_invite(self.user_a.email)
        self.assertEqual(staff.status_code, 400)
        self.assertIn("already has an account", str(staff.data))
        self.assertEqual(self.staff_invite("fresh@example.org").status_code, 201)
        again = self.staff_invite("fresh@example.org")
        self.assertIn("pending invite", str(again.data))

    def test_invites_per_admin_are_limited(self):
        with rates(invite_send_user="3/hour", invite_send_recipient="100/day"), \
                self.captureOnCommitCallbacks(execute=True):
            codes = [self.staff_invite(f"person{i}@example.org").status_code for i in range(4)]
        self.assertEqual(codes, [201, 201, 201, 429])
        self.assertEqual(len(mail.outbox), 3)

    def test_invites_to_one_recipient_are_limited_across_schools(self):
        # Another school's admin can't use invites to flood someone's inbox either.
        admin_b = User.objects.create_user(username="admin_b", email="admin.b@beta.test", password="x")
        Profile.objects.create(user=admin_b, school=self.school_b, role=Profile.Role.ADMIN)
        client_b = self.authed_client(admin_b)
        with rates(invite_send_user="100/hour", invite_send_recipient="2/day"):
            first = self.staff_invite("target@example.org")
            second = self.staff_invite("TARGET@example.org ", client=client_b)
            third = self.parent_invite("target@example.org")
        self.assertEqual((first.status_code, second.status_code, third.status_code), (201, 201, 429))

    def test_renewing_an_invite_is_limited(self):
        invite_id = self.staff_invite("renew.me@example.org").data["id"]
        with rates(invite_send_user="100/hour", invite_send_recipient="2/day"):
            codes = [self.admin.post(f"/api/invites/{invite_id}/renew/").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_reading_and_cancelling_invites_are_not_limited(self):
        with rates(invite_send_user="1/hour", invite_send_recipient="1/day"):
            invite_id = self.staff_invite("x@example.org").data["id"]
            for _ in range(3):
                self.assertEqual(self.admin.get("/api/invites/").status_code, 200)
            self.assertEqual(self.admin.delete(f"/api/invites/{invite_id}/").status_code, 204)
