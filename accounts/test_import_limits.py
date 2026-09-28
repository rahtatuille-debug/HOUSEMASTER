"""
B-2: the bulk staff import counts against the same invite limits as
single invites (F-12): per admin per hour and per recipient address per
day, across all schools. When a limit is reached the import still creates
what it may and lists the other rows as deferred, so the admin can run
the same sheet again later. Deferred rows are logged by row number only.
"""
from unittest.mock import patch

from django.test import override_settings
from rest_framework.settings import api_settings

from activity.models import ActivityLog
from students.models import SchoolClass, YearGroup

from .models import Invite, Profile
from .test_staff_import import sheet
from .tests import SchoolScopedAPITestCase


def rates(**values):
    return patch.dict(api_settings.DEFAULT_THROTTLE_RATES, values)


def people(n, start=1, domain="alpha.test"):
    return [[f"Person {i}", f"person{i}@{domain}", "teacher", "", ""] for i in range(start, start + n)]


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class StaffImportLimitTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        SchoolClass.objects.create(year_group=year, name="7A")

    def run_import(self, rows, client=None, commit=True):
        data = {"file": sheet(*rows), "commit": "true" if commit else "false", "send_emails": "true"}
        return (client or self.admin).post("/api/import/staff/", data, format="multipart")

    def test_import_bigger_than_the_hourly_admin_limit_defers_the_rest(self):
        with rates(invite_send_user="3/hour"):
            response = self.run_import(people(5))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["row"] for p in response.data["people"]], [2, 3, 4])
        self.assertEqual([d["row"] for d in response.data["deferred"]], [5, 6])
        self.assertTrue(all("per hour" in d["reason"] for d in response.data["deferred"]))
        self.assertEqual(Invite.objects.filter(school=self.school_a).count(), 3)

    def test_running_the_same_sheet_later_creates_the_deferred_rows(self):
        with rates(invite_send_user="3/hour"):
            self.run_import(people(5))
        # An hour later the admin runs the same sheet: the three invited
        # already are skipped and the two deferred ones are created.
        with rates(invite_send_user="3/hour"), patch("rest_framework.throttling.SimpleRateThrottle.timer",
                                                    return_value=10**10):
            again = self.run_import(people(5))
        self.assertEqual([p["row"] for p in again.data["people"]], [5, 6])
        self.assertEqual(len(again.data["skipped"]), 3)
        self.assertEqual(again.data["deferred"], [])

    def test_recipient_daily_limit_applies_across_schools(self):
        admin_b = self.make_school_b_admin()
        with rates(invite_send_recipient="1/day"):
            self.run_import([["Shared Person", "shared@example.org", "teacher", "", ""]])
            response = self.run_import([["Shared Person", "shared@example.org", "teacher", "", ""]], client=admin_b)
        self.assertEqual(response.data["people"], [])
        self.assertEqual([d["row"] for d in response.data["deferred"]], [2])
        self.assertIn("per day", response.data["deferred"][0]["reason"])
        self.assertFalse(Invite.objects.filter(school=self.school_b).exists())

    def test_single_invites_and_the_import_share_one_budget(self):
        with rates(invite_send_user="3/hour"):
            for i in (1, 2):
                self.admin.post("/api/invites/", {"name": f"One {i}", "email": f"one{i}@alpha.test", "role": "teacher"},
                                format="json")
            response = self.run_import(people(3))
            self.assertEqual(len(response.data["people"]), 1)
            self.assertEqual(len(response.data["deferred"]), 2)
            # And the import's invites count against single invites too.
            single = self.admin.post("/api/invites/", {"name": "Late", "email": "late@alpha.test", "role": "teacher"},
                                     format="json")
        self.assertEqual(single.status_code, 429)

    def test_another_admins_limit_is_independent(self):
        second = self.second_school_a_admin()
        with rates(invite_send_user="3/hour"):
            self.run_import(people(4))
            response = self.run_import(people(3, start=10), client=second)
        self.assertEqual(len(response.data["people"]), 3)
        self.assertEqual(response.data["deferred"], [])

    def test_preview_shows_what_would_be_deferred_without_using_the_budget(self):
        with rates(invite_send_user="3/hour"):
            preview = self.run_import(people(5), commit=False)
            again = self.run_import(people(5), commit=False)
            committed = self.run_import(people(5))
        for response in (preview, again, committed):
            self.assertEqual([d["row"] for d in response.data["deferred"]], [5, 6])
        self.assertEqual(len(committed.data["people"]), 3)

    def test_deferred_rows_are_logged_by_row_number_without_addresses(self):
        with rates(invite_send_user="1/hour"):
            self.run_import(people(3))
        entry = ActivityLog.objects.get(action="staff.imported")
        self.assertIn("rows 3, 4", entry.summary)
        self.assertEqual(entry.details.get("deferred_rows"), [3, 4])
        for i in (2, 3):
            self.assertNotIn(f"person{i}@", entry.summary)
            self.assertNotIn(f"person{i}@", str(entry.details))

    def test_only_invites_that_were_created_are_emailed(self):
        from django.core import mail

        with rates(invite_send_user="2/hour"), self.captureOnCommitCallbacks(execute=True):
            self.run_import(people(4))
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["person1@alpha.test", "person2@alpha.test"])

    # helpers

    def make_school_b_admin(self):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username="admin_b", email="admin.b@beta.test", password="pass1234")
        Profile.objects.create(user=user, school=self.school_b, role=Profile.Role.ADMIN)
        return self.authed_client(user)

    def second_school_a_admin(self):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username="admin_a2", email="admin.a2@alpha.test", password="pass1234")
        Profile.objects.create(user=user, school=self.school_a, role=Profile.Role.ADMIN)
        return self.authed_client(user)
