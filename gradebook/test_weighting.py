"""Assessment types and how they weight a subject's term result."""
from django.test import SimpleTestCase

from accounts.tests import SchoolScopedAPITestCase
from students.models import SchoolClass, Student, YearGroup

from .models import AssessmentType, Grade, Subject, Term
from .systems import term_summary
from .weighting import subject_percent


class WeightingRuleTests(SimpleTestCase):
    W = {1: 30.0, 2: 70.0}

    def test_types_are_combined_by_weight(self):
        # CATs average 60, exam 90: 0.3 * 60 + 0.7 * 90 = 81
        self.assertAlmostEqual(subject_percent([(50, 1), (70, 1), (90, 2)], self.W), 81)

    def test_missing_types_are_left_out_rather_than_counted_as_zero(self):
        self.assertAlmostEqual(subject_percent([(60, 1)], self.W), 60)

    def test_untyped_marks_count_with_the_average_weight(self):
        # untyped 40 gets weight 50 (the mean of 30 and 70): (0.3*60 + 0.7*90 + 0.5*40) / 1.5
        self.assertAlmostEqual(subject_percent([(60, 1), (90, 2), (40, None)], self.W), (18 + 63 + 20) / 1.5)

    def test_no_types_means_a_plain_average(self):
        self.assertAlmostEqual(subject_percent([(50, None), (70, None)], {}), 60)
        self.assertIsNone(subject_percent([], self.W))

    def test_a_type_from_elsewhere_counts_as_untyped(self):
        self.assertAlmostEqual(subject_percent([(50, 99), (70, None)], {}), 60)


class AssessmentTypeTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        klass = SchoolClass.objects.create(year_group=YearGroup.objects.create(school=self.school_a, name="Form 1"),
                                           name="1 East")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.kid = Student.objects.create(school=self.school_a, school_class=klass, first_name="Ann", last_name="X")
        self.assign(self.user_a, klass, None)

    def test_admin_sets_types_and_they_weight_results_everywhere(self):
        cat = self.admin.post("/api/assessment-types/", {"name": "CAT", "weight": 30}).data["id"]
        exam = self.admin.post("/api/assessment-types/", {"name": "End-term exam", "weight": 70}).data["id"]
        for score, kind in ((50, cat), (70, cat), (90, exam)):
            self.assertEqual(self.client_a.post("/api/grades/", {"student": self.kid.id, "subject": self.maths.id,
                                                                 "term": self.term.id, "score": score,
                                                                 "assessment_type": kind}).status_code, 201)
        self.assertEqual(term_summary(self.kid, self.term)["subjects"][0]["percent"], 81.0)
        profile = self.admin.get(f"/api/students/{self.kid.id}/profile/").data
        self.assertEqual(profile["grades_by_term"][0]["average"], 81.0)
        self.assertEqual({r["assessment"] for r in profile["grades_by_term"][0]["grades"]}, {"CAT", "End-term exam"})
        perf = self.admin.get("/api/analytics/performance/", {"scope": "student", "id": self.kid.id}).data
        self.assertEqual(perf["trend"][0]["student"], 81.0)

    def test_teachers_need_approval_and_weights_are_checked(self):
        self.assertEqual(self.client_a.post("/api/assessment-types/", {"name": "CAT", "weight": 30}).status_code, 202)
        self.assertFalse(AssessmentType.objects.exists())
        self.assertEqual(self.admin.post("/api/assessment-types/", {"name": "CAT", "weight": 130}).status_code, 400)

    def test_another_schools_type_cannot_be_used(self):
        other = AssessmentType.objects.create(school=self.school_b, name="CAT", weight=30)
        response = self.admin.post("/api/grades/", {"student": self.kid.id, "subject": self.maths.id,
                                                   "term": self.term.id, "score": 50, "assessment_type": other.id})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Grade.objects.exists())

    def test_setup_creates_the_systems_types(self):
        body = {"name": "Alpha", "education_system": "844", "grading_scale": "kcse", "report_tone": "formal",
                "year_groups": [{"name": "Form 1", "classes": ["1 East"]}], "subjects": ["Maths"],
                "terms": [{"name": "Term 1", "start_date": "2026-01-06", "end_date": "2026-04-03"}],
                "assessments": [{"name": "CAT", "weight": 30}, {"name": "End-term exam", "weight": 70}]}
        response = self.admin.post("/api/setup/finish/", body, format="json")
        self.assertEqual(response.data["created"]["assessment_types"], 2)
        self.assertEqual(list(AssessmentType.objects.filter(school=self.school_a).values_list("name", "weight")),
                         [("CAT", 30), ("End-term exam", 70)])
