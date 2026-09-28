"""
F-19: minor hardening.

- HSTS lasts 30 days by default (env-overridable), without preload.
- "Today" is the school's day in Nairobi, not UTC: between 00:00 and 03:00
  Nairobi time the UTC date is still yesterday.
- A teacher asking for subject entries for a class they don't teach gets
  403, like everywhere else, not an empty 200.
"""
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone

from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from gradebook.models import Subject, Term
from students.models import SchoolClass, Student, YearGroup

from .test_settings_guard import PRODUCTION_ENV, import_settings


def at_utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


class HSTSTests(SimpleTestCase):
    def test_hsts_is_thirty_days_without_preload_by_default(self):
        code_env = dict(PRODUCTION_ENV)
        ok, stderr = import_settings(code_env)
        self.assertTrue(ok, stderr)
        import subprocess
        import sys

        from .test_settings_guard import BASE_DIR

        def value(env):
            import os

            clean = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "SECURE_"))}
            clean.update({"HOUSEMASTER_SKIP_DOTENV": "1", **env})
            out = subprocess.run([sys.executable, "-c", "import housemaster.settings as s; "
                                  "print(s.SECURE_HSTS_SECONDS, getattr(s, 'SECURE_HSTS_PRELOAD', False))"],
                                 cwd=BASE_DIR, env=clean, capture_output=True, text=True)
            return out.stdout.split()

        self.assertEqual(value(PRODUCTION_ENV), ["2592000", "False"])
        self.assertEqual(value({**PRODUCTION_ENV, "SECURE_HSTS_SECONDS": "31536000"}), ["31536000", "False"])


class LocalDateTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.user_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.student = Student.objects.create(school=self.school_a, first_name="A", last_name="B",
                                              school_class=self.klass)

    def test_time_zone_is_nairobi(self):
        self.assertEqual(settings.TIME_ZONE, "Africa/Nairobi")
        self.assertTrue(settings.USE_TZ)

    def test_today_after_midnight_in_nairobi_is_the_new_day(self):
        # 23:30 UTC on Wednesday 4 March is 02:30 on Thursday in Nairobi, and
        # 21:30 UTC is 00:30 on Thursday.
        for moment in (at_utc(2026, 3, 4, 23, 30), at_utc(2026, 3, 4, 21, 30)):
            with patch("django.utils.timezone.now", return_value=moment):
                self.assertEqual(timezone.localdate().isoformat(), "2026-03-05")
                dashboard = self.client_a.get("/api/dashboard/").data
                self.assertEqual(str(dashboard["attendance_today"]["date"]), "2026-03-05")
                self.assertTrue(dashboard["attendance_today"]["is_today"])

    def test_register_taken_in_nairobi_after_midnight_counts_as_today(self):
        AttendanceRecord.objects.create(student=self.student, date=datetime(2026, 3, 5).date(), status="present")
        maths = Subject.objects.create(school=self.school_a, name="Maths")
        teacher = self.user_b
        teacher.profile.school = self.school_a
        teacher.profile.save()
        self.assign(teacher, self.klass, maths)
        with patch("django.utils.timezone.now", return_value=at_utc(2026, 3, 4, 22, 0)):
            home = self.client_b.get("/api/teacher-home/").data
        self.assertTrue(home["classes"][0]["register_taken_today"], home)


class SubjectReportAccessTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.taught = SchoolClass.objects.create(year_group=year, name="7A")
        self.other = SchoolClass.objects.create(year_group=year, name="7B")
        self.subject = Subject.objects.create(school=self.school_a, name="Maths")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.assign(self.user_a, self.taught, self.subject)

    def params(self, klass):
        return {"term": self.term.id, "subject": self.subject.id, "school_class": klass.id}

    def test_teacher_gets_403_for_a_class_they_do_not_teach(self):
        self.assertEqual(self.client_a.get("/api/subject-reports/", self.params(self.other)).status_code, 403)
        post = self.client_a.post("/api/subject-reports/", {**self.params(self.other), "entries": []}, format="json")
        self.assertEqual(post.status_code, 403)

    def test_teacher_and_admin_can_still_use_their_classes(self):
        self.assertEqual(self.client_a.get("/api/subject-reports/", self.params(self.taught)).status_code, 200)
        admin = self.authed_client(self.admin_a)
        self.assertEqual(admin.get("/api/subject-reports/", self.params(self.other)).status_code, 200)
