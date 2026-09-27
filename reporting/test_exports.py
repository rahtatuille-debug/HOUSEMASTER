"""Exports: class list, grades, attendance (Excel) and finalized reports (PDF)."""
from datetime import date
from io import BytesIO

import openpyxl

from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Subject, Term
from students.models import SchoolClass, Student, YearGroup

from .models import StudentReport


class ExportTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.c7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.c7b = SchoolClass.objects.create(year_group=year, name="7B")
        self.term = Term.objects.create(school=self.school_a, name="Term 1", start_date="2026-01-05",
                                        end_date="2026-04-01")
        maths = Subject.objects.create(school=self.school_a, name="Maths")
        art = Subject.objects.create(school=self.school_a, name="Art")
        self.ann = Student.objects.create(school=self.school_a, first_name="Zoë", last_name="Ångström",
                                          school_class=self.c7a, external_id="S1", medical_notes="Asthma")
        self.ben = Student.objects.create(school=self.school_a, first_name="Ben", last_name="Two",
                                          school_class=self.c7a, external_id="S2")
        Student.objects.create(school=self.school_a, first_name="Cy", last_name="Other", school_class=self.c7b)
        Grade.objects.create(student=self.ann, subject=maths, term=self.term, score=80)
        Grade.objects.create(student=self.ann, subject=art, term=self.term, score=60)
        AttendanceRecord.objects.create(student=self.ann, date=date(2026, 2, 2), status="present")
        AttendanceRecord.objects.create(student=self.ann, date=date(2026, 2, 3), status="absent")
        StudentReport.objects.create(
            student=self.ann, term=self.term, progress_summary="s", status="finalized",
            report_comment="Zoë has made “excellent” progress — well done. It’s been a great term.",
        )
        StudentReport.objects.create(student=self.ben, term=self.term, progress_summary="s",
                                     report_comment="Draft", status="draft")
        self.assign(self.user_a, self.c7a, maths)

    def get(self, what, client=None, **params):
        return (client or self.admin_client_a).get(f"/api/exports/{what}/", params)

    def sheet(self, response, name):
        return [list(r) for r in openpyxl.load_workbook(BytesIO(response.content))[name].iter_rows(values_only=True)]

    def test_class_list(self):
        response = self.get("class-list", school_class=self.c7a.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("class-list-7a.xlsx", response["Content-Disposition"])
        rows = self.sheet(response, "Class list")
        self.assertEqual(rows[0][:3], ["Admission no.", "Last name", "First name"])
        self.assertEqual([r[0] for r in rows[1:]], ["S2", "S1"])  # by last name: Two, Ångström sorts after
        self.assertEqual(rows[2][-1], "Asthma")
        self.assertTrue(ActivityLog.objects.filter(action="export.downloaded").exists())

    def test_grades(self):
        rows = self.sheet(self.get("grades", school_class=self.c7a.id, term=self.term.id), "Grades (%)")
        self.assertEqual(rows[0], ["Admission no.", "Last name", "First name", "Art", "Maths", "Average", "Level"])
        ann = next(r for r in rows if r[0] == "S1")
        self.assertEqual(ann[3:], [60.0, 80.0, 70.0, "ME"])

    def test_attendance(self):
        response = self.get("attendance", school_class=self.c7a.id, start="2026-02-01", end="2026-02-28")
        summary = self.sheet(response, "Summary")
        ann = next(r for r in summary if r[0] == "S1")
        self.assertEqual(ann[3:], [2, 1, 1, 0, 0, 50.0])
        by_day = self.sheet(response, "By day")
        self.assertEqual(next(r for r in by_day if r[0] == "S1")[2:4], ["P", "A"])

    def test_attendance_needs_valid_dates(self):
        self.assertEqual(self.get("attendance", school_class=self.c7a.id, start="x", end="y").status_code, 400)
        self.assertEqual(self.get("attendance", school_class=self.c7a.id, start="2026-03-01",
                                  end="2026-02-01").status_code, 400)

    def test_reports_pdf_has_one_page_per_finalized_report_and_handles_unicode(self):
        response = self.get("reports", school_class=self.c7a.id, term=self.term.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertEqual(response.content.count(b"/Type /Page\n"), 1)  # Ben's report is only a draft

    def test_no_finalized_reports(self):
        StudentReport.objects.update(status="draft")
        self.assertEqual(self.get("reports", school_class=self.c7a.id, term=self.term.id).status_code, 404)

    def test_teacher_exports_own_class_only(self):
        self.assertEqual(self.get("class-list", client=self.client_a, school_class=self.c7a.id).status_code, 200)
        self.assertEqual(self.get("class-list", client=self.client_a, school_class=self.c7b.id).status_code, 403)

    def test_other_school_cannot_export(self):
        self.make_admin(self.user_b)
        self.assertEqual(self.get("class-list", client=self.client_b, school_class=self.c7a.id).status_code, 404)
        self.assertEqual(self.get("grades", client=self.client_b, school_class=self.c7a.id,
                                  term=self.term.id).status_code, 404)

    def test_parents_cannot_export(self):
        from django.contrib.auth.models import User

        from guardians.models import Guardian

        user = User.objects.create_user(username="p@x.test", email="p@x.test", password="x")
        Guardian.objects.create(user=user, school=self.school_a).students.add(self.ann)
        response = self.get("class-list", client=self.authed_client(user), school_class=self.c7a.id)
        self.assertEqual(response.status_code, 403)
