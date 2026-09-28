"""
F-13: an email address belongs to at most one account, whatever its case,
enforced by the database, and a race between two sign-ups ends in one
account and one friendly 400 rather than a 500 or two half-usable
accounts.
"""
from importlib import import_module
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from accounts.models import Invite
from guardians.models import GuardianInvite
from students.models import SchoolClass, Student, YearGroup
from students.setup_views import RegisterSchoolSerializer

from .serializers import AcceptInviteSerializer
from .tests import SchoolScopedAPITestCase

SIGNUP = {"school_name": "Gamma School", "name": "Some One", "password": "Long-Enough-Pass-1", "accept_privacy": True}


class UniqueEmailTests(SchoolScopedAPITestCase):
    def test_database_refuses_the_same_email_in_another_case(self):
        User.objects.create_user(username="first", email="Person@Example.org", password="x")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="second", email="person@example.ORG", password="x")

    def test_accounts_without_an_email_are_still_allowed(self):
        User.objects.create_user(username="no-email-1", email="", password="x")
        User.objects.create_user(username="no-email-2", email="", password="x")

    def test_registration_race_ends_in_one_account_and_a_friendly_400(self):
        # Simulate the second of two simultaneous sign-ups: its own "is this
        # email free?" check passed before the first one saved.
        User.objects.create_user(username="racer@example.org", email="racer@example.org", password="x")
        with patch.object(RegisterSchoolSerializer, "validate_email", lambda self, value: value.strip().lower()):
            response = APIClient().post("/api/schools/register/", {**SIGNUP, "email": "RACER@example.org"},
                                        format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"email": ["An account with this email already exists. Sign in instead."]})
        self.assertEqual(User.objects.filter(email__iexact="racer@example.org").count(), 1)
        from students.models import School
        self.assertFalse(School.objects.filter(name="Gamma School").exists())

    def test_staff_invite_accept_race_is_a_friendly_400(self):
        invite = Invite.objects.create(school=self.school_a, email="late@example.org", name="Late Comer",
                                       role="teacher", invited_by=self.admin_a)
        User.objects.create_user(username="someone-else", email="LATE@example.org", password="x")
        with patch.object(AcceptInviteSerializer, "validate_token", lambda self, value: setattr(self, "_invite", invite) or value):
            response = APIClient().post("/api/invites/accept/", {"token": invite.token, "password": "Long-Enough-Pass-1",
                                                                 "accept_privacy": True}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", str(response.data["token"]))

    def test_parent_invite_accept_race_is_a_friendly_400(self):
        from guardians.serializers import AcceptGuardianInviteSerializer

        year = YearGroup.objects.create(school=self.school_a, name="Y7")
        kid = Student.objects.create(school=self.school_a, first_name="A", last_name="B",
                                     school_class=SchoolClass.objects.create(year_group=year, name="7A"))
        invite = GuardianInvite.objects.create(school=self.school_a, email="parent.late@example.org", name="P L",
                                               invited_by=self.admin_a)
        invite.students.add(kid)
        User.objects.create_user(username="dup", email="Parent.Late@example.org", password="x")
        with patch.object(AcceptGuardianInviteSerializer, "validate_token",
                          lambda self, value: setattr(self, "_invite", invite) or value):
            response = APIClient().post("/api/guardian-invites/accept/",
                                        {"token": invite.token, "password": "Long-Enough-Pass-1", "accept_privacy": True},
                                        format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", str(response.data["token"]))


class DuplicateEmailPreflightTests(SchoolScopedAPITestCase):
    def test_preflight_names_user_ids_only(self):
        migration = import_module("accounts.migrations.0013_unique_email")
        user_model = MagicMock()
        rows = user_model.objects.exclude.return_value.annotate.return_value.values.return_value
        rows.annotate.return_value.filter.return_value.values_list.return_value = ["a@example.org"]
        user_model.objects.annotate.return_value.filter.return_value.order_by.return_value.values_list \
            .return_value = [4, 9]
        apps = MagicMock()
        apps.get_model.return_value = user_model
        with self.assertRaises(RuntimeError) as ctx:
            migration.refuse_duplicate_emails(apps, None)
        message = str(ctx.exception)
        self.assertIn("4, 9", message)
        self.assertNotIn("a@example.org", message)
        self.assertIn("check_duplicate_emails", message)
