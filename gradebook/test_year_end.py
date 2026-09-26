"""End of year: locking terms, and moving students up a year."""
from datetime import date

from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from attendance.models import AttendanceRecord
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

from .models import Grade, Subject, Term


class TermLockTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        self.make_admin(self.user_b)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.student = Student.objects.create(school=self.school_a, first_name="A", last_name="B", school_class=klass)
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.term = Term.objects.create(school=self.school_a, name="Term 1", start_date=date(2026, 1, 5),
                                        end_date=date(2026, 4, 1))
        self.grade = Grade.objects.create(student=self.student, subject=self.maths, term=self.term, score=50)
        self.record = AttendanceRecord.objects.create(student=self.student, date=date(2026, 2, 2), status="present")
        self.report = StudentReport.objects.create(student=self.student, term=self.term, progress_summary="s",
                                                   report_comment="c", status="submitted")
        self.assert_ok(self.admin_client_a.post(f"/api/terms/{self.term.id}/lock/"))

    def assert_ok(self, response):
        self.assertLess(response.status_code, 300, getattr(response, "data", None))

    def test_locked_term_blocks_everything_even_for_admins(self):
        c = self.admin_client_a
        self.assertEqual(c.patch(f"/api/grades/{self.grade.id}/", {"score": "90"}).status_code, 400)
        self.assertEqual(c.delete(f"/api/grades/{self.grade.id}/").status_code, 400)
        self.assertEqual(c.post("/api/grades/", {"student": self.student.id, "subject": self.maths.id,
                                                 "term": self.term.id, "score": "1"}).status_code, 400)
        self.assertEqual(c.patch(f"/api/attendance/{self.record.id}/", {"status": "absent"}).status_code, 400)
        self.assertEqual(c.post("/api/attendance/", {"student": self.student.id, "date": "2026-03-03",
                                                     "status": "absent"}).status_code, 400)
        self.assertEqual(c.post(f"/api/reports/{self.report.id}/finalize/").status_code, 400)
        self.assertEqual(c.patch(f"/api/reports/{self.report.id}/", {"report_comment": "x"}).status_code, 400)
        self.assertEqual(c.patch(f"/api/terms/{self.term.id}/", {"name": "Renamed"}).status_code, 400)
        self.assertEqual(c.delete(f"/api/terms/{self.term.id}/").status_code, 400)
        self.grade.refresh_from_db()
        self.assertEqual(self.grade.score, 50)

    def test_attendance_outside_the_locked_term_is_fine(self):
        response = self.admin_client_a.post("/api/attendance/", {"student": self.student.id, "date": "2026-05-05",
                                                                  "status": "present"})
        self.assertEqual(response.status_code, 201)

    def test_unlocking_allows_changes_again_and_is_logged(self):
        self.assert_ok(self.admin_client_a.post(f"/api/terms/{self.term.id}/unlock/"))
        self.assertEqual(self.admin_client_a.patch(f"/api/grades/{self.grade.id}/", {"score": "90"}).status_code, 200)
        self.assertTrue(ActivityLog.objects.filter(action="term.locked").exists())
        self.assertTrue(ActivityLog.objects.filter(action="term.unlocked").exists())

    def test_only_admins_lock_and_only_own_school(self):
        self.assertEqual(self.client_a.post(f"/api/terms/{self.term.id}/unlock/").status_code, 403)
        self.assertEqual(self.client_b.post(f"/api/terms/{self.term.id}/unlock/").status_code, 404)

    def test_term_list_shows_lock(self):
        term = next(t for t in self.admin_client_a.get("/api/terms/").data if t["id"] == self.term.id)
        self.assertTrue(term["is_locked"])


class PromotionTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        y7 = YearGroup.objects.create(school=self.school_a, name="Year 7")
        y8 = YearGroup.objects.create(school=self.school_a, name="Year 8")
        self.c7 = SchoolClass.objects.create(year_group=y7, name="7A")
        self.c8 = SchoolClass.objects.create(year_group=y8, name="8A")
        self.s7 = [Student.objects.create(school=self.school_a, first_name=f"S{i}", last_name="7", school_class=self.c7)
                   for i in range(3)]
        self.s8 = [Student.objects.create(school=self.school_a, first_name=f"T{i}", last_name="8", school_class=self.c8)
                   for i in range(2)]
        self.gone = Student.objects.create(school=self.school_a, first_name="Old", last_name="Leaver",
                                           school_class=self.c7, is_active=False)

    def promote(self, moves, commit, client=None):
        return (client or self.admin_client_a).post("/api/promotion/", {"moves": moves, "commit": commit},
                                                    format="json")

    def test_preview_changes_nothing(self):
        response = self.promote([{"from_class": self.c7.id, "to_class": self.c8.id},
                                 {"from_class": self.c8.id, "to_class": None}], commit=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([(m["from_name"], m["to_name"], m["students"]) for m in response.data["moves"]],
                         [("7A", "8A", 3), ("8A", "Leaving school", 2)])
        self.assertEqual(Student.objects.filter(school_class=self.c7, is_active=True).count(), 3)

    def test_chain_moves_everyone_exactly_once(self):
        self.promote([{"from_class": self.c7.id, "to_class": self.c8.id},
                      {"from_class": self.c8.id, "to_class": None}], commit=True)
        for s in self.s7:
            s.refresh_from_db()
            self.assertEqual((s.school_class, s.is_active), (self.c8, True))
        for s in self.s8:
            s.refresh_from_db()
            self.assertFalse(s.is_active)  # left, history kept
            self.assertEqual(s.school_class, self.c8)
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.school_class, self.c7)  # already inactive: untouched
        self.assertTrue(ActivityLog.objects.filter(action="school.year_end").exists())

    def test_swap(self):
        self.promote([{"from_class": self.c7.id, "to_class": self.c8.id},
                      {"from_class": self.c8.id, "to_class": self.c7.id}], commit=True)
        self.assertEqual(set(Student.objects.filter(school_class=self.c8, is_active=True)), set(self.s7))
        self.assertEqual(set(Student.objects.filter(school_class=self.c7, is_active=True)), set(self.s8))

    def test_only_admins_and_only_own_classes(self):
        self.assertEqual(self.promote([{"from_class": self.c7.id, "to_class": self.c8.id}], True,
                                      client=self.client_a).status_code, 403)
        other = SchoolClass.objects.create(year_group=YearGroup.objects.create(school=self.school_b, name="Y"), name="Z")
        self.assertEqual(self.promote([{"from_class": self.c7.id, "to_class": other.id}], True).status_code, 400)
        self.assertEqual(Student.objects.filter(school_class=other).count(), 0)

    def test_duplicate_and_empty_plans_rejected(self):
        self.assertEqual(self.promote([], True).status_code, 400)
        self.assertEqual(self.promote([{"from_class": self.c7.id, "to_class": self.c8.id},
                                       {"from_class": self.c7.id, "to_class": None}], True).status_code, 400)
