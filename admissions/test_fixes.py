"""
Fixes from the known-gaps list for admissions (B-1 to B-5). Test data is made up.
"""
import re
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from activity.models import ActivityLog

from .models import Application
from .tests import AdmissionsFixture


def confirm_link(message):
    return re.search(r"/apply/confirm/(\S+)", message.body).group(1)


class ConfirmEmailTests(AdmissionsFixture):
    """B-1."""

    def test_an_application_waits_unconfirmed_and_one_email_goes_out(self):
        response = self.apply(confirm=False)
        self.assertEqual(response.status_code, 202, response.data)
        self.assertNotIn("reference", response.data)
        app = self.application()
        self.assertIsNone(app.confirmed_at)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["priya@example.test"])
        self.assertIn("Alpha Academy", message.subject + message.body)  # says who it's from
        for detail in ("Zara", "Patel", "Hill Primary", "2015"):  # nothing about the child
            self.assertNotIn(detail, message.subject + message.body)
        token = confirm_link(message)
        self.assertNotIn(token, str(Application.objects.values().get()))  # only a hash is kept
        self.assertFalse(ActivityLog.objects.filter(action="admissions.applied").exists())

    def test_admins_see_only_confirmed_applications_and_unconfirmed_ones_separately(self):
        self.apply(confirm=False)
        app = self.application()
        self.assertEqual(self.admin.get("/api/admissions/applications/").data, [])
        self.assertEqual(self.admin.get(f"/api/admissions/applications/{app.id}/").status_code, 404)
        unconfirmed = self.admin.get("/api/admissions/applications/", {"unconfirmed": 1}).data
        self.assertEqual([a["id"] for a in unconfirmed], [app.id])
        summary = self.admin.get("/api/admissions/applications/summary/").data
        self.assertEqual((summary["counts"], summary["unconfirmed"]), ({}, 1))
        self.assertEqual(self.admin.post(f"/api/admissions/applications/{app.id}/enrol/",
                                         {"school_class": self.c7a.id}, format="json").status_code, 404)

    def test_confirming_releases_it_once(self):
        self.apply(confirm=False)
        token = confirm_link(mail.outbox[0])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.public.post(f"/api/admissions/confirm/{token}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["reference"].startswith("A"))
        self.assertIsNotNone(self.application().confirmed_at)
        self.assertIn(response.data["reference"], mail.outbox[-1].body)  # the receipt
        self.assertEqual(len(self.admin.get("/api/admissions/applications/").data), 1)
        self.assertTrue(ActivityLog.objects.filter(action="admissions.applied").exists())
        self.assertEqual(self.public.post(f"/api/admissions/confirm/{token}/").status_code, 400)  # single use
        self.assertEqual(self.public.post("/api/admissions/confirm/not-a-token/").status_code, 400)

    def test_links_expire_and_old_unconfirmed_applications_are_removed(self):
        self.apply(confirm=False)
        token = confirm_link(mail.outbox[0])
        Application.objects.update(confirm_expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.public.post(f"/api/admissions/confirm/{token}/").status_code, 400)
        self.apply(confirm=False, first_name="Omar", parent_email="o@example.test")  # still in time
        expired = self.application()
        out = StringIO()
        call_command("purge_applications", stdout=out)
        self.assertIn("1 unconfirmed", out.getvalue())
        self.assertEqual(Application.objects.count(), 2)  # dry run
        call_command("purge_applications", "--apply", stdout=StringIO())
        self.assertEqual(list(Application.objects.values_list("first_name", flat=True)), ["Omar"])
        self.assertNotIn(expired.first_name, out.getvalue())  # counts only
