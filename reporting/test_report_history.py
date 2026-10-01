"""
Old report cards keep the class, curriculum and grading scale the student had
when the report was finalized, even after they move up a year. And the heavy
pages read only the terms they need.
"""
from datetime import date
from io import BytesIO

from django.contrib.auth.models import User

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Grade, Subject, Term
from gradebook.systems import term_summary
from guardians.models import Guardian
from reporting.analytics import SchoolGrades
from reporting.models import StudentReport
from students.models import School, SchoolClass, Student, YearGroup
from support.services import warning_signs


class ReportHistoryTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        School.objects.filter(pk=self.school_a.pk).update(education_system="british", grading_scale="igcse9")
        self.school_a.refresh_from_db()
        self.admin = self.authed_client(self.admin_a)
        self.y11 = YearGroup.objects.create(school=self.school_a, name="Year 11", order=0)
        # The sixth form grades in letters.
        self.y12 = YearGroup.objects.create(school=self.school_a, name="Year 12", order=1, grading_scale="igcse")
        self.c11 = SchoolClass.objects.create(year_group=self.y11, name="11A")
        self.c12 = SchoolClass.objects.create(year_group=self.y12, name="12A")
        self.term = Term.objects.create(school=self.school_a, name="Summer 2026", start_date=date(2026, 4, 20),
                                        end_date=date(2026, 7, 10))
        self.maths = Subject.objects.create(school=self.school_a, name="Mathematics")
        self.kid = Student.objects.create(school=self.school_a, first_name="Ola", last_name="B", school_class=self.c11)
        Grade.objects.create(student=self.kid, subject=self.maths, term=self.term, score=95)
        self.report = StudentReport.objects.create(student=self.kid, term=self.term, status="submitted",
                                                   progress_summary="Good.", report_comment="A good term.")

    def finalize(self):
        response = self.admin.post(f"/api/reports/{self.report.id}/finalize/")
        self.assertEqual(response.status_code, 200, response.data)
        self.report.refresh_from_db()

    def move_up(self):
        self.admin.post("/api/promotion/", {"moves": [{"from_class": self.c11.id, "to_class": self.c12.id}],
                                            "commit": True}, format="json")
        self.kid.refresh_from_db()
        self.assertEqual(self.kid.school_class, self.c12)

    def pdf_text(self):
        from pypdf import PdfReader

        from reporting.exports import reports_pdf

        content, _ = reports_pdf(self.school_a, [Student.objects.get(pk=self.kid.pk)], self.term)
        return " ".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)

    def test_finalizing_records_the_class_and_scale(self):
        self.finalize()
        self.assertEqual((self.report.school_class, self.report.class_name, self.report.education_system,
                          self.report.grading_scale), (self.c11, "Year 11 · 11A", "british", "igcse9"))

    def test_finalizing_a_whole_class_records_it_too(self):
        response = self.admin.post("/api/reports/finalize-class/", {"school_class": self.c11.id, "term": self.term.id},
                                   format="json")
        self.assertEqual(response.data["count"], 1, response.data)
        self.report.refresh_from_db()
        self.assertEqual(self.report.class_name, "Year 11 · 11A")

    def test_an_old_report_card_still_shows_the_class_and_grades_of_the_time(self):
        self.finalize()
        self.move_up()
        summary = term_summary(self.kid, self.term, self.report)
        self.assertEqual((summary["scale"], summary["subjects"][0]["level"]), ("igcse9", "9"))
        text = self.pdf_text()
        self.assertIn("Year 11 · 11A", text)
        self.assertNotIn("12A", text)
        # Without the recorded report the current (letter) scale would be used.
        self.assertEqual(term_summary(self.kid, self.term)["subjects"][0]["level"], "A*")

    def test_parents_see_the_grades_of_the_time(self):
        self.finalize()
        self.move_up()
        parent = User.objects.create_user(username="p@a.test", email="p@a.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="P").students.add(self.kid)
        data = self.authed_client(parent).get(f"/api/guardian-students/{self.kid.id}/term-summary/",
                                              {"term": self.term.id}).data
        self.assertEqual(data["subjects"][0]["level"], "9")

    def test_moving_up_records_the_class_on_reports_finalized_before_it_was_recorded(self):
        StudentReport.objects.filter(pk=self.report.pk).update(status="finalized")  # an older report: nothing recorded
        self.move_up()
        self.report.refresh_from_db()
        self.assertEqual(self.report.class_name, "Year 11 · 11A")
        self.assertIn("Year 11 · 11A", self.pdf_text())


class EightFourFourHistoryTests(SchoolScopedAPITestCase):
    """8-4-4 positions on an old report card rank against the form the student was in at the time."""

    def test_positions_after_moving_up(self):
        School.objects.filter(pk=self.school_a.pk).update(education_system="844", grading_scale="kcse")
        self.school_a.refresh_from_db()
        f3 = YearGroup.objects.create(school=self.school_a, name="Form 3", order=0)
        f4 = YearGroup.objects.create(school=self.school_a, name="Form 4", order=1)
        east3 = SchoolClass.objects.create(year_group=f3, name="3 East")
        east4 = SchoolClass.objects.create(year_group=f4, name="4 East")
        term = Term.objects.create(school=self.school_a, name="T3 2025", start_date=date(2025, 9, 1))
        maths = Subject.objects.create(school=self.school_a, name="Mathematics")
        kids = []
        for name, score in (("Top", 90), ("Mid", 60), ("Low", 30)):
            s = Student.objects.create(school=self.school_a, first_name=name, last_name="K", school_class=east3)
            Grade.objects.create(student=s, subject=maths, term=term, score=score)
            report = StudentReport.objects.create(student=s, term=term, status="finalized", progress_summary="x",
                                                  report_comment="x")
            report.record_class()
            report.save()
            kids.append((s, report))
        # Next year: Mid moves to Form 4 with students who weren't in their form that term.
        mid, mid_report = kids[1]
        Student.objects.filter(pk=mid.pk).update(school_class=east4)
        newcomer = Student.objects.create(school=self.school_a, first_name="New", last_name="K", school_class=east4)
        Grade.objects.create(student=newcomer, subject=maths, term=term, score=99)
        mid.refresh_from_db()
        positions = term_summary(mid, term, mid_report)["positions"]
        self.assertEqual(positions["stream"], {"position": 2, "of": 3})


class RecentTermsTests(SchoolScopedAPITestCase):
    def test_loading_only_recent_terms_gives_the_same_warning_signs(self):
        School.objects.filter(pk=self.school_a.pk).update(education_system="british", grading_scale="igcse9")
        self.school_a.refresh_from_db()
        klass = SchoolClass.objects.create(year_group=YearGroup.objects.create(school=self.school_a, name="Y9"),
                                           name="9A")
        maths = Subject.objects.create(school=self.school_a, name="Mathematics")
        terms = [Term.objects.create(school=self.school_a, name=f"T{i}", start_date=date(2024 + i // 3, 1 + i % 3 * 4, 1))
                 for i in range(6)]
        for n in range(8):
            s = Student.objects.create(school=self.school_a, first_name=f"S{n}", last_name="K", school_class=klass)
            for i, term in enumerate(terms):
                Grade.objects.create(student=s, subject=maths, term=term, score=80 - (n * i * 3) % 60)
        full = SchoolGrades(self.school_a)
        for term in terms:
            recent = SchoolGrades(self.school_a, recent=True, term_id=term.id)
            self.assertEqual(recent.graded_terms, full.graded_terms)
            self.assertLessEqual({k[1] for k in recent.marks}, {term.id, *(t.id for t in terms if t != term)})
            self.assertEqual(warning_signs(recent, term, list(full.students)),
                             warning_signs(full, term, list(full.students)), term.name)
        latest = SchoolGrades(self.school_a, recent=True)
        self.assertEqual(latest.term(None), terms[-1])
        self.assertEqual({k[1] for k in latest.marks}, {terms[-1].id, terms[-2].id})

    def test_bad_requests_are_refused_before_loading_marks(self):
        teacher = self.authed_client(self.user_a)
        with self.assertNumQueries(4):  # sign-in and profile only
            self.assertEqual(teacher.get("/api/analytics/performance/", {"scope": "school"}).status_code, 403)
