"""
Scoping tests for AttendanceRecordViewSet.
"""
from students.models import Student
from accounts.tests import SchoolScopedAPITestCase

from .models import AttendanceRecord


class AttendanceScopingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.student_a = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno"
        )
        self.student_b = Student.objects.create(
            school=self.school_b, first_name="Brian", last_name="Kiptoo"
        )
        self.record_a = AttendanceRecord.objects.create(
            student=self.student_a, date="2026-02-01", status="present"
        )
        self.record_b = AttendanceRecord.objects.create(
            student=self.student_b, date="2026-02-01", status="present"
        )

    def test_list_only_returns_own_schools_records(self):
        response = self.client_a.get("/api/attendance/")
        ids = [row["id"] for row in response.data]
        self.assertIn(self.record_a.id, ids)
        self.assertNotIn(self.record_b.id, ids)

    def test_cannot_retrieve_another_schools_record(self):
        response = self.client_a.get(f"/api/attendance/{self.record_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_create_rejects_spoofed_student(self):
        response = self.client_a.post(
            "/api/attendance/",
            {"student": self.student_b.id, "date": "2026-02-02", "status": "absent"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            AttendanceRecord.objects.filter(student=self.student_b, date="2026-02-02").exists()
        )

    def test_create_succeeds_for_own_student(self):
        response = self.client_a.post(
            "/api/attendance/",
            {"student": self.student_a.id, "date": "2026-02-02", "status": "late"},
        )
        self.assertEqual(response.status_code, 201)

    def test_update_rejects_repointing_to_another_schools_student(self):
        # Use a date student_b doesn't already have a record for, so this
        # exercises the scoping check rather than tripping the unrelated
        # (student, date) unique-together constraint first.
        response = self.client_a.patch(
            f"/api/attendance/{self.record_a.id}/",
            {"student": self.student_b.id, "date": "2026-03-15"},
        )
        self.assertEqual(response.status_code, 403)
        self.record_a.refresh_from_db()
        self.assertEqual(self.record_a.student_id, self.student_a.id)

    def test_one_record_per_student_per_day_still_enforced_within_school(self):
        # Not a scoping test per se, but worth pinning: the unique_together
        # constraint should still surface as a normal validation error, not
        # a scoping-related 403.
        response = self.client_a.post(
            "/api/attendance/",
            {"student": self.student_a.id, "date": "2026-02-01", "status": "late"},
        )
        self.assertEqual(response.status_code, 400)
