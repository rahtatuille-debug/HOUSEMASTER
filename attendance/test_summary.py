"""The Attendance page opens on every class's register for the day: present, late, absent and how many are marked."""
from students.models import SchoolClass, Student, YearGroup
from accounts.tests import SchoolScopedAPITestCase

from .models import AttendanceRecord


class SummaryTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Grade 7", order=0)
        self.c7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.c7b = SchoolClass.objects.create(year_group=year, name="7B")
        SchoolClass.objects.create(year_group=year, name="7C")  # no students: left out
        kids = [Student.objects.create(school=self.school_a, first_name=n, last_name="K", school_class=c)
                for n, c in [("Ann", self.c7a), ("Ben", self.c7a), ("Cy", self.c7a), ("Di", self.c7b)]]
        Student.objects.create(school=self.school_a, first_name="Gone", last_name="K", school_class=self.c7a,
                               is_active=False)
        AttendanceRecord.objects.create(student=kids[0], date="2026-10-07", status="present")
        AttendanceRecord.objects.create(student=kids[1], date="2026-10-07", status="absent")
        AttendanceRecord.objects.create(student=kids[2], date="2026-10-07", status="late")
        AttendanceRecord.objects.create(student=kids[3], date="2026-10-06", status="absent")  # another day
        other = Student.objects.create(school=self.school_b, first_name="Zed", last_name="B")
        AttendanceRecord.objects.create(student=other, date="2026-10-07", status="absent")

    def test_admin_sees_every_class_for_the_day(self):
        response = self.admin.get("/api/attendance/summary/", {"date": "2026-10-07"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["date"], "2026-10-07")
        rows = {r["name"]: r for r in response.data["classes"]}
        self.assertEqual(list(rows), ["7A", "7B"])
        a = rows["7A"]
        self.assertEqual((a["students"], a["marked"], a["present"], a["late"], a["absent"]), (3, 3, 1, 1, 1))
        self.assertEqual((rows["7B"]["students"], rows["7B"]["marked"]), (1, 0))
        self.assertEqual(response.data["totals"], {"students": 4, "marked": 3, "present": 1, "late": 1, "absent": 1,
                                                   "excused": 0, "not_taken": 1})

    def test_a_teacher_sees_only_their_classes(self):
        self.assign(self.user_a, self.c7b, None)
        rows = self.client_a.get("/api/attendance/summary/", {"date": "2026-10-07"}).data["classes"]
        self.assertEqual([r["name"] for r in rows], ["7B"])

    def test_another_school_sees_nothing_of_ours(self):
        self.make_admin(self.user_b)
        data = self.client_b.get("/api/attendance/summary/", {"date": "2026-10-07"}).data
        self.assertEqual(data["classes"], [])

    def test_a_bad_date_is_refused_and_no_date_means_today(self):
        self.assertEqual(self.admin.get("/api/attendance/summary/", {"date": "07/10/2026"}).status_code, 400)
        self.assertEqual(self.admin.get("/api/attendance/summary/").status_code, 200)
