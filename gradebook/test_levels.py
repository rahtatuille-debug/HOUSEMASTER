"""CBC performance levels: the scales, the school setting, and where levels show up."""
from io import BytesIO

import openpyxl
from django.test import SimpleTestCase

from accounts.tests import SchoolScopedAPITestCase
from students.models import SchoolClass, Student, YearGroup

from .levels import level_for, levels_key, with_level
from .models import Grade, Subject, Term


class LevelScaleTests(SimpleTestCase):
    def test_four_level_boundaries(self):
        self.assertEqual([level_for(p, "cbc4") for p in (100, 80, 79.9, 50, 49.9, 30, 29.9, 0)],
                         ["EE", "EE", "ME", "ME", "AE", "AE", "BE", "BE"])

    def test_eight_level_boundaries(self):
        self.assertEqual([level_for(p, "cbc8") for p in (90, 89, 75, 74, 58, 57, 41, 40, 31, 30, 21, 20, 11, 10, 0)],
                         ["EE1", "EE2", "EE2", "ME1", "ME1", "ME2", "ME2", "AE1", "AE1", "AE2", "AE2",
                          "BE1", "BE1", "BE2", "BE2"])

    def test_percent_only_and_missing_values(self):
        self.assertEqual(level_for(72, "percent"), "")
        self.assertEqual(level_for(None, "cbc4"), "")
        self.assertEqual(with_level(72.4, "cbc4"), "72% · ME")
        self.assertEqual(with_level(72.4, "percent"), "72%")
        self.assertEqual(levels_key("cbc4"), "EE 80–100%, ME 50–79%, AE 30–49%, BE 0–29%")


class SchoolLevelTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Grade 7")
        self.klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        maths = Subject.objects.create(school=self.school_a, name="Maths")
        for name, score in (("Ann", 85), ("Ben", 65), ("Cy", 40), ("Dee", 10)):
            s = Student.objects.create(school=self.school_a, school_class=self.klass, first_name=name, last_name="X")
            Grade.objects.create(student=s, subject=maths, term=self.term, score=score)

    def test_schools_default_to_four_levels_and_me_sends_the_bands(self):
        school = self.admin_client.get("/api/me/").data["school"]
        self.assertEqual(school["grading_scale"], "cbc4")
        self.assertEqual([b["code"] for b in school["levels"]], ["EE", "ME", "AE", "BE"])

    def test_admin_switches_to_eight_levels(self):
        response = self.admin_client.patch(f"/api/schools/{self.school_a.id}/", {"grading_scale": "cbc8"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.admin_client.get("/api/me/").data["school"]["levels"]), 8)
        self.assertEqual(self.admin_client.patch(f"/api/schools/{self.school_a.id}/",
                                                 {"grading_scale": "letters"}).status_code, 400)

    def test_teachers_need_approval_to_change_the_scale(self):
        response = self.client_a.patch(f"/api/schools/{self.school_a.id}/", {"grading_scale": "percent"})
        self.assertEqual(response.status_code, 202)
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.grading_scale, "cbc4")

    def test_spread_chart_counts_students_per_level(self):
        data = self.admin_client.get("/api/analytics/performance/",
                                     {"scope": "class", "id": self.klass.id, "term": self.term.id}).data
        self.assertEqual([(b["band"], b["students"]) for b in data["distribution"]],
                         [("BE", 1), ("AE", 1), ("ME", 1), ("EE", 1)])

    def test_percentage_schools_keep_ten_percent_bands(self):
        self.school_a.grading_scale = "percent"
        self.school_a.save()
        data = self.admin_client.get("/api/analytics/performance/",
                                     {"scope": "class", "id": self.klass.id, "term": self.term.id}).data
        self.assertEqual(data["distribution"][0]["band"], "Below 40%")

    def test_grades_export_adds_a_level_column(self):
        response = self.admin_client.get("/api/exports/grades/", {"school_class": self.klass.id, "term": self.term.id})
        ws = openpyxl.load_workbook(BytesIO(response.content)).active
        rows = list(ws.iter_rows(values_only=True))
        self.assertEqual(rows[0][-1], "Level")
        self.assertEqual({r[2]: r[-1] for r in rows[1:]}, {"Ann": "EE", "Ben": "ME", "Cy": "AE", "Dee": "BE"})

    def test_report_card_pdf_builds_with_levels(self):
        from reporting.exports import reports_pdf
        from reporting.models import StudentReport

        ann = Student.objects.get(first_name="Ann")
        StudentReport.objects.create(student=ann, term=self.term, progress_summary="s", report_comment="c",
                                     status="finalized")
        for scale in ("cbc4", "cbc8", "percent"):
            self.school_a.grading_scale = scale
            content, count = reports_pdf(self.school_a, [ann], self.term)
            self.assertEqual(count, 1)
            self.assertTrue(content.startswith(b"%PDF"))
