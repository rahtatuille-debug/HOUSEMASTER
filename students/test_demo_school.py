"""The demo school command: what it creates, and that it never touches real schools."""
import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Grade
from reporting.models import StudentReport

from .management.commands.seed_demo_school import DOMAIN, SCHOOL_NAME
from .models import School, Student

PASSWORD = "Demo-Pass-for-tests"


def run(*args):
    out = StringIO()
    with patch.dict(os.environ, {"DEMO_PASSWORD": PASSWORD}):
        call_command("seed_demo_school", *args, stdout=out)
    return out.getvalue()


class DemoSchoolTests(SchoolScopedAPITestCase):
    def login(self, email):
        client = APIClient()
        response = client.post("/api/token/", {"email": email, "password": PASSWORD})
        self.assertEqual(response.status_code, 200, email)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client

    def test_skips_without_a_password(self):
        with patch.dict(os.environ, {"DEMO_PASSWORD": ""}):
            call_command("seed_demo_school", stdout=StringIO())
        self.assertFalse(School.objects.filter(name=SCHOOL_NAME).exists())

    def test_rejects_a_short_password(self):
        with patch.dict(os.environ, {"DEMO_PASSWORD": "short"}), self.assertRaises(CommandError):
            call_command("seed_demo_school", stdout=StringIO())

    def test_builds_a_full_school_and_only_once(self):
        run()
        school = School.objects.get(name=SCHOOL_NAME)
        self.assertGreater(Student.objects.filter(school=school, is_active=True).count(), 130)
        self.assertGreater(Grade.objects.filter(student__school=school).count(), 2000)
        self.assertIn("already exists", run())
        self.assertEqual(School.objects.filter(name=SCHOOL_NAME).count(), 1)
        # Every demo account is on the reserved demo domain.
        demo_users = User.objects.filter(profile__school=school) | User.objects.filter(guardian__school=school)
        self.assertTrue(all(u.email.endswith(f"@{DOMAIN}") for u in demo_users))

    def test_demo_logins_work_and_see_filled_screens(self):
        run()
        admin = self.login(f"principal@{DOMAIN}")
        dashboard = admin.get("/api/dashboard/").data
        self.assertGreater(dashboard["reports_waiting"]["count"], 0)
        self.assertEqual(dashboard["requests_waiting"], 1)
        self.assertGreater(len(admin.get("/api/analytics/performance/", {"scope": "school"}).data["trend"]), 0)
        teacher = self.login(f"m.njeri@{DOMAIN}")
        self.assertEqual(len(teacher.get("/api/me/").data["assignments"]), 3)
        parent = self.login(f"parent@{DOMAIN}")
        self.assertGreater(len(parent.get("/api/guardian-students/").data), 0)
        self.assertGreater(len(parent.get("/api/conversations/").data), 0)

    def test_real_schools_are_never_touched_or_visible(self):
        run()
        run("--reset")
        self.assertTrue(School.objects.filter(id=self.school_a.id).exists())
        self.assertTrue(User.objects.filter(id=self.user_a.id).exists())
        # A real school's admin sees nothing of the demo school.
        self.make_admin(self.user_a)
        data = self.client_a.get("/api/dashboard/").data
        self.assertEqual(data["students_without_parent"]["total_students"], 0)
        self.assertEqual(self.client_a.get("/api/students/").data, [])

    def test_reset_rebuilds(self):
        run()
        first_id = School.objects.get(name=SCHOOL_NAME).id
        self.assertIn("Deleted the old", run("--reset"))
        self.assertNotEqual(School.objects.get(name=SCHOOL_NAME).id, first_id)


class SystemDemoTests(SchoolScopedAPITestCase):
    """The 8-4-4, British, IB and American demo schools."""
    login = DemoSchoolTests.login

    def test_one_demo_school_per_system_each_in_its_own_style(self):
        from .demo_systems import DEMOS, domain

        run()
        self.assertEqual(set(School.objects.filter(name__startswith="HouseMaster Demo")
                             .values_list("education_system", flat=True)), {"cbc", "844", "british", "ib", "american"})
        markers = {"844": "mean_grade", "british": "subjects", "ib": "ib_total", "american": "gpa"}
        for spec in DEMOS:
            school = School.objects.get(name=spec["name"])
            admin = self.login(f"principal@{domain(spec)}")
            me = admin.get("/api/me/").data
            self.assertEqual((me["school"]["name"], me["role"]), (spec["name"], "admin"))
            students = admin.get("/api/students/").data
            self.assertEqual(len(students), Student.objects.filter(school=school).count())
            # Each demo school sees only its own students.
            self.assertTrue(all(s["school"] == school.id for s in students))
            parent = self.login(f"parent@{domain(spec)}")
            child = parent.get("/api/guardian-students/").data[0]
            report = StudentReport.objects.get(student_id=child["id"], status="finalized")
            summary = admin.get(f"/api/students/{child['id']}/term-summary/", {"term": report.term_id}).data
            self.assertEqual(summary["system"], spec["key"])
            self.assertIsNotNone(summary.get(markers[spec["key"]]), spec["key"])
            teacher = self.login(f"{spec['staff'][1][1]}@{domain(spec)}")
            self.assertGreater(len(teacher.get("/api/me/").data["assignments"]), 0)
        # Finalized report cards download as PDFs.
        ib = School.objects.get(name="HouseMaster Demo IB School")
        report = StudentReport.objects.filter(student__school=ib, status="finalized").first()
        pdf = self.login(f"principal@ib.{DOMAIN}").get("/api/exports/reports/", {
            "school_class": report.student.school_class_id, "term": report.term_id})
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_missing_demo_schools_are_added_and_reset_rebuilds_them(self):
        run()
        School.objects.filter(name="HouseMaster Demo IB School").delete()
        User.objects.filter(email__iendswith=f"@ib.{DOMAIN}").delete()
        out = run()
        self.assertIn("Created HouseMaster Demo IB School", out)
        self.assertIn("HouseMaster Demo Secondary already exists", out)
        before = School.objects.get(name="HouseMaster Demo Secondary").id
        run("--reset")
        self.assertNotEqual(School.objects.get(name="HouseMaster Demo Secondary").id, before)
        self.assertEqual(School.objects.filter(name__startswith="HouseMaster Demo").count(), 5)


class DemoAfterMigrateTests(SchoolScopedAPITestCase):
    """Deploys run migrate, which builds the demo when DEMO_PASSWORD is set."""

    def migrate_hook(self, argv, password):
        from django.apps import apps

        from .apps import seed_demo_after_migrate
        with patch.dict(os.environ, {"DEMO_PASSWORD": password}), patch("sys.argv", argv), \
                patch("sys.stdout", StringIO()):
            seed_demo_after_migrate(sender=apps.get_app_config("students"))

    def test_migrate_builds_the_demo_when_the_password_is_set(self):
        self.migrate_hook(["manage.py", "migrate"], PASSWORD)
        self.assertTrue(School.objects.filter(name=SCHOOL_NAME).exists())

    def test_nothing_happens_without_a_password_or_outside_migrate(self):
        self.migrate_hook(["manage.py", "migrate"], "")
        self.migrate_hook(["manage.py", "test"], PASSWORD)
        self.assertFalse(School.objects.filter(name=SCHOOL_NAME).exists())
