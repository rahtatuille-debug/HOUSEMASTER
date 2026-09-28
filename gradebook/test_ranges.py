"""
F-10: grades and attendance can't hold impossible values.

Grades: 0 <= score <= max_score and max_score > 0, on create and update,
enforced by the serializer and by database constraints. Attendance: no more
than one day in the future (the school's local date) and not more than five
years back unless one of the school's terms covers the date.
"""
import io
from datetime import date, timedelta
from unittest.mock import MagicMock

import openpyxl
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Subject, Term
from students.models import SchoolClass, Student, YearGroup


class RangeTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.user_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.student = Student.objects.create(school=self.school_a, first_name="Amina", last_name="Otieno",
                                              school_class=self.klass, external_id="S1")
        self.subject = Subject.objects.create(school=self.school_a, name="Maths")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.today = timezone.localdate()

    def grade(self, score, max_score=100):
        return self.client_a.post("/api/grades/", {"student": self.student.id, "subject": self.subject.id,
                                                   "term": self.term.id, "score": score, "max_score": max_score},
                                  format="json")

    def mark(self, day):
        return self.client_a.post("/api/attendance/", {"student": self.student.id, "date": day.isoformat(),
                                                       "status": "present"}, format="json")

    # --- grades ----------------------------------------------------------

    def test_impossible_grades_are_refused_on_create(self):
        for score, max_score in [(150, 100), (-5, 100), (5, 0), (5, -10), (0.5, 0)]:
            response = self.grade(score, max_score)
            self.assertEqual(response.status_code, 400, (score, max_score, response.data))
        self.assertFalse(Grade.objects.exists())

    def test_boundaries_are_allowed(self):
        self.assertEqual(self.grade(0).status_code, 201)
        self.assertEqual(self.grade(100).status_code, 201)
        self.assertEqual(self.grade(12.5, 20).status_code, 201)

    def test_impossible_grades_are_refused_on_update(self):
        grade_id = self.grade(80).data["id"]
        url = f"/api/grades/{grade_id}/"
        self.assertEqual(self.client_a.patch(url, {"score": 150}, format="json").status_code, 400)
        self.assertEqual(self.client_a.patch(url, {"score": -1}, format="json").status_code, 400)
        # Lowering the maximum below the existing score is refused too.
        self.assertEqual(self.client_a.patch(url, {"max_score": 50}, format="json").status_code, 400)
        self.assertEqual(self.client_a.patch(url, {"max_score": 0}, format="json").status_code, 400)
        self.assertEqual(Grade.objects.get(pk=grade_id).score, 80)
        self.assertEqual(self.client_a.patch(url, {"score": 90}, format="json").status_code, 200)

    def test_database_refuses_impossible_grades_too(self):
        for score, max_score in [(150, 100), (-5, 100), (5, 0)]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Grade.objects.create(student=self.student, subject=self.subject, term=self.term,
                                     score=score, max_score=max_score)

    # --- attendance ------------------------------------------------------

    def test_attendance_far_in_the_future_is_refused(self):
        response = self.mark(self.today + timedelta(days=400))
        self.assertEqual(response.status_code, 400)
        self.assertIn("date", response.data)
        self.assertEqual(self.mark(self.today + timedelta(days=2)).status_code, 400)

    def test_attendance_today_and_tomorrow_are_allowed(self):
        self.assertEqual(self.mark(self.today).status_code, 201)
        self.assertEqual(self.mark(self.today + timedelta(days=1)).status_code, 201)

    def test_attendance_long_ago_needs_a_term_covering_it(self):
        old = self.today - timedelta(days=6 * 365)
        self.assertEqual(self.mark(old).status_code, 400)
        Term.objects.create(school=self.school_a, name="Old term", start_date=old - timedelta(days=10),
                            end_date=old + timedelta(days=10))
        self.assertEqual(self.mark(old).status_code, 201)

    def test_moving_attendance_into_the_future_is_refused(self):
        record_id = self.mark(self.today).data["id"]
        response = self.client_a.patch(f"/api/attendance/{record_id}/",
                                       {"date": (self.today + timedelta(days=30)).isoformat()}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_import_refuses_future_attendance(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Students"
        ws.append(["student_id", "first_name", "last_name", "class", "year_group"])
        ws.append(["S1", "Amina", "Otieno", "7A", "Year 7"])
        att = wb.create_sheet("Attendance")
        att.append(["student_id", "date", "status"])
        att.append(["S1", self.today + timedelta(days=400), "present"])
        att.append(["S1", self.today, "present"])
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        out.name = "import.xlsx"
        response = self.client_a.post("/api/import/", {"file": out, "commit": "true"}, format="multipart")
        self.assertIn(response.status_code, (200, 201), response.data)
        self.assertEqual(AttendanceRecord.objects.filter(student=self.student).count(), 1)
        self.assertTrue(any("future" in e["message"] for e in response.data["errors"]), response.data["errors"])


class RangePreflightTests(SchoolScopedAPITestCase):
    """The migration adding the constraints stops, naming row IDs only, if production has bad rows."""

    def test_preflight_lists_ids_and_no_personal_data(self):
        from importlib import import_module

        migration = import_module("gradebook.migrations.0007_grade_ranges")
        grade_model = MagicMock()
        grade_model.objects.filter.return_value.order_by.return_value.values_list.return_value = [3, 17, 42]
        apps = MagicMock()
        apps.get_model.return_value = grade_model
        with self.assertRaises(RuntimeError) as ctx:
            migration.refuse_out_of_range_grades(apps, None)
        message = str(ctx.exception)
        self.assertIn("3 grade", message)
        self.assertIn("3, 17, 42", message)
        self.assertIn("preflight_range_checks.sql", message)

    def test_preflight_passes_on_clean_data(self):
        from importlib import import_module

        migration = import_module("gradebook.migrations.0007_grade_ranges")
        grade_model = MagicMock()
        grade_model.objects.filter.return_value.order_by.return_value.values_list.return_value = []
        apps = MagicMock()
        apps.get_model.return_value = grade_model
        migration.refuse_out_of_range_grades(apps, None)
