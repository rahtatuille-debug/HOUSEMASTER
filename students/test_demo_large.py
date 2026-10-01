"""
The large demo school: a British secondary with five years of history,
built small here (the real one has about 1,000 students).
"""
import os
from datetime import date
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.management import call_command

from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Term
from guardians.models import Guardian
from reporting.models import StudentReport
from support.models import SupportConcern

from . import demo_large
from .models import School, Student

TODAY = date(2026, 10, 1)


class LargeDemoTests(SchoolScopedAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.summary = demo_large.build(make_password("Demo-Pass-for-tests"), today=TODAY, scale=0.1)
        cls.school = School.objects.get(name=demo_large.NAME)

    def test_five_school_years_of_terms_with_old_ones_locked(self):
        terms = list(Term.objects.filter(school=self.school).order_by("start_date"))
        self.assertEqual(terms[0].name, "Autumn term 2021/22")
        self.assertEqual(len(terms), 18)  # five full years and this year's three
        self.assertTrue(all(t.is_locked for t in terms if t.end_date < date(2025, 9, 1)))
        self.assertFalse(any(t.is_locked for t in terms if t.start_date >= date(2025, 9, 1)))

    def test_every_finished_term_has_marks_and_finalized_reports(self):
        for term in Term.objects.filter(school=self.school, end_date__lt=TODAY):
            self.assertTrue(Grade.objects.filter(term=term).exists(), term.name)
            reports = StudentReport.objects.filter(term=term)
            self.assertTrue(reports.exists(), term.name)
            self.assertFalse(reports.exclude(status="finalized").exists())
        current = Term.objects.get(school=self.school, name="Autumn term 2026/27")
        self.assertTrue(Grade.objects.filter(term=current).exists())
        self.assertFalse(StudentReport.objects.filter(term=current).exists())

    def test_students_move_up_graduate_and_join(self):
        active = Student.objects.filter(school=self.school, is_active=True)
        self.assertFalse(active.filter(school_class__isnull=True).exists())
        graduates = Student.objects.filter(school=self.school, is_active=False, graduated_on__isnull=False)
        self.assertTrue(graduates.exists())
        self.assertEqual(set(graduates.values_list("graduated_on__month", flat=True)), {7})
        self.assertEqual(set(active.values_list("enrolled_on__year", flat=True)), set(range(2021, 2027)))

    def test_old_reports_show_the_form_of_the_time(self):
        veteran = Guardian.objects.get(user__email=f"parent@{demo_large.DOMAIN}").students.first()
        self.assertEqual(veteran.school_class.year_group.name, "Year 13")
        first = StudentReport.objects.filter(student=veteran).order_by("term__start_date").first()
        self.assertEqual(first.term.name, "Autumn term 2021/22")
        self.assertTrue(first.class_name.startswith("Year 8 · 8"), first.class_name)
        self.assertEqual(first.grading_scale, "igcse9")
        self.assertEqual(StudentReport.objects.filter(student=veteran).count(), 15)

    def test_attendance_is_this_school_year_only(self):
        dates = AttendanceRecord.objects.filter(student__school=self.school).values_list("date", flat=True)
        self.assertTrue(dates)
        self.assertGreaterEqual(min(dates), date(2026, 9, 3))
        self.assertLess(max(dates), TODAY)

    def test_logins_and_a_few_students_marked_for_support(self):
        for local in ("principal", "teacher", "parent"):
            response = self.client.post("/api/token/", {"email": f"{local}@{demo_large.DOMAIN}",
                                                        "password": "Demo-Pass-for-tests"})
            self.assertEqual(response.status_code, 200, local)
        self.assertTrue(0 < SupportConcern.objects.filter(school=self.school).count() <= 6)
        self.assertIn("Log in as principal@", self.summary)

    def test_year_groups_in_school_order(self):
        """Year 7 comes before Year 10, not after it (they used to be sorted by name)."""
        token = self.client.post("/api/token/", {"email": f"principal@{demo_large.DOMAIN}",
                                                 "password": "Demo-Pass-for-tests"}).data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        expected = [f"Year {n}" for n in range(7, 14)]
        self.assertEqual([y["name"] for y in self.client.get("/api/year-groups/").data], expected)
        school = self.client.get("/api/analytics/performance/", {"scope": "school"}).data
        self.assertEqual([g["name"] for g in school["groups"]], expected)


class LargeDemoCommandTests(SchoolScopedAPITestCase):
    def run_command(self, env, *args):
        out, err = StringIO(), StringIO()
        build = demo_large.build
        with patch.dict(os.environ, env), patch.object(demo_large, "build",
                                                      side_effect=lambda h: build(h, today=TODAY, scale=0.05)):
            call_command("seed_large_demo", *args, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_refuses_on_production_and_without_a_password(self):
        self.assertIn("Refusing", self.run_command({"DEMO_PASSWORD": "Demo-Pass-for-tests", "ALLOW_DEMO_SEED": ""}))
        self.assertIn("isn't set", self.run_command({"DEMO_PASSWORD": "", "ALLOW_DEMO_SEED": "1"}))
        self.assertFalse(School.objects.filter(name=demo_large.NAME).exists())

    def test_builds_once_and_rebuilds_with_reset(self):
        env = {"DEMO_PASSWORD": "Demo-Pass-for-tests", "ALLOW_DEMO_SEED": "1"}
        self.assertIn("Created", self.run_command(env))
        self.assertIn("already exists", self.run_command(env))
        first = School.objects.get(name=demo_large.NAME).id
        self.assertIn("Created", self.run_command(env, "--reset"))
        self.assertNotEqual(School.objects.get(name=demo_large.NAME).id, first)
        self.assertEqual(School.objects.filter(name=demo_large.NAME).count(), 1)

    def test_never_runs_after_migrate(self):
        from students.apps import seed_demo_after_migrate

        with patch.dict(os.environ, {"DEMO_PASSWORD": "Demo-Pass-for-tests", "ALLOW_DEMO_SEED": "1"}), \
                patch("sys.argv", ["manage.py", "migrate"]), patch("django.core.management.call_command") as call:
            seed_demo_after_migrate(sender=None)
        self.assertNotIn("seed_large_demo", [c.args[0] for c in call.call_args_list])


