"""
Fixes from the known-gaps list for admissions (B-1 to B-5). Test data is made up.
"""
import re
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from unittest import skipUnless

from django.db import connection
from django.test import TransactionTestCase
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


class DuplicateTests(AdmissionsFixture):
    """B-2."""

    def test_sending_the_same_child_twice_makes_one_application_and_one_email(self):
        first = self.apply(confirm=False)
        second = self.apply(confirm=False)
        self.assertEqual((first.status_code, second.status_code), (202, 202))
        self.assertEqual(first.data, second.data)  # nothing tells them apart
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_the_same_child_after_confirming_is_still_one_application(self):
        self.apply()
        self.apply(first_name=" zara ", last_name="PATEL", parent_email="Priya@Example.test")
        self.assertEqual(Application.objects.count(), 1)

    def test_a_different_child_or_a_closed_application_is_not_a_duplicate(self):
        self.apply()
        self.apply(first_name="Omar")  # a sibling
        self.assertEqual(Application.objects.count(), 2)
        Application.objects.filter(first_name="Zara").update(status="declined")
        self.apply()  # applying again after a decision
        self.assertEqual(Application.objects.filter(first_name="Zara").count(), 2)

    def test_an_expired_link_is_sent_again_rather_than_a_second_application(self):
        self.apply(confirm=False)
        Application.objects.update(confirm_expires_at=timezone.now() - timedelta(minutes=1))
        self.apply(confirm=False)
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self.public.post(f"/api/admissions/confirm/{confirm_link(mail.outbox[-1])}/").status_code, 200)

    def test_a_child_who_is_already_a_student_is_not_enrolled_again(self):
        from students.models import Student

        existing = Student.objects.create(school=self.school_a, first_name="Zara", last_name="Patel",
                                          date_of_birth="2015-03-02", school_class=self.c7a)
        self.apply()
        app = self.application()
        Application.objects.filter(pk=app.pk).update(status="offered")
        response = self.admin.post(f"/api/admissions/applications/{app.id}/enrol/", {"school_class": self.c7a.id},
                                   format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(int(response.data["existing_student"]), existing.id)
        self.assertEqual(Student.objects.filter(first_name="Zara").count(), 1)
        self.assertEqual(self.application().status, "offered")


@skipUnless(connection.vendor == "postgresql", "needs a database with concurrent writers (production's Postgres); "
                                               "SQLite's shared in-memory test database refuses the second writer")
class DuplicateRaceTests(TransactionTestCase):
    """B-2: two copies of the same form arriving at the same moment make one application."""

    def test_two_at_once(self):
        import threading

        from rest_framework.test import APIClient

        from students.models import School, YearGroup

        from .models import AdmissionsSettings

        school = School.objects.create(name="Race School")
        year = YearGroup.objects.create(school=school, name="Year 7")
        settings = AdmissionsSettings.objects.create(school=school, is_open=True)
        body = {"year_group": year.id, "first_name": "Ann", "last_name": "Lee", "date_of_birth": "2015-01-01",
                "parent_name": "Pat Lee", "parent_email": "pat@example.test", "parent_phone": "0700000000",
                "consent": True}
        barrier, codes = threading.Barrier(2), []

        def send():
            try:
                barrier.wait()
                codes.append(APIClient().post(f"/api/admissions/apply/{settings.token}/", body, format="json")
                             .status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=send) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(codes, [202, 202])
        self.assertEqual(Application.objects.filter(school=school).count(), 1)
