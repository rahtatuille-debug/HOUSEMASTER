"""
Scoping tests for StudentReportViewSet, including the custom `generate`
action.

`generate` gets its own dedicated coverage because it doesn't go through
the generic SchoolScopedViewSetMixin.get_queryset() filtering at all — it's
a custom @action that does its own manual Student.objects.get() /
Term.objects.get() lookups (see reporting/views.py). Before scoping was
added, this endpoint could generate a report for any student in any school
by guessing an ID — this is the regression this test class exists to catch.

The real generate_report() call hits the live Gemini API, so it's mocked
here — these tests are about the *scoping* around report generation, not
the AI output itself (that's covered by manual verification per the
project's hardening notes, and would be a good candidate for a separate,
explicitly-marked "hits a real API key" test later if ever needed).
"""
from unittest.mock import patch

from students.models import Student
from gradebook.models import Term
from accounts.tests import SchoolScopedAPITestCase

from .models import StudentReport


class StudentReportScopingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.student_a = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno"
        )
        self.student_b = Student.objects.create(
            school=self.school_b, first_name="Brian", last_name="Kiptoo"
        )
        self.term_a = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.term_b = Term.objects.create(school=self.school_b, name="Term 1 2026")

        self.report_a = StudentReport.objects.create(
            student=self.student_a,
            term=self.term_a,
            progress_summary="Doing well.",
            report_comment="Great term.",
        )
        self.report_b = StudentReport.objects.create(
            student=self.student_b,
            term=self.term_b,
            progress_summary="Doing well.",
            report_comment="Great term.",
        )

    def test_list_only_returns_own_schools_reports(self):
        response = self.client_a.get("/api/reports/")
        ids = [row["id"] for row in response.data]
        self.assertIn(self.report_a.id, ids)
        self.assertNotIn(self.report_b.id, ids)

    def test_cannot_retrieve_another_schools_report(self):
        response = self.client_a.get(f"/api/reports/{self.report_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_cannot_edit_another_schools_report(self):
        response = self.client_a.patch(
            f"/api/reports/{self.report_b.id}/", {"status": "finalized"}
        )
        self.assertEqual(response.status_code, 404)
        self.report_b.refresh_from_db()
        self.assertEqual(self.report_b.status, "draft")

    def test_create_rejects_spoofed_student(self):
        response = self.client_a.post(
            "/api/reports/",
            {
                "student": self.student_b.id,
                "term": self.term_a.id,
                "progress_summary": "x",
                "report_comment": "x",
            },
        )
        self.assertEqual(response.status_code, 403)


class GenerateActionScopingTests(SchoolScopedAPITestCase):
    """
    This is the highest-priority test class in the whole suite per the
    hardening plan: the `generate` action previously had no scoping at
    all, and it's a custom @action that the generic queryset-filtering
    mixin doesn't automatically protect.
    """

    def setUp(self):
        super().setUp()
        self.student_a = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno"
        )
        self.student_b = Student.objects.create(
            school=self.school_b, first_name="Brian", last_name="Kiptoo"
        )
        self.term_a = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.term_b = Term.objects.create(school=self.school_b, name="Term 1 2026")

    @patch("reporting.views.generate_report")
    def test_generate_for_own_student_and_term_succeeds(self, mock_generate):
        mock_generate.return_value = StudentReport.objects.create(
            student=self.student_a,
            term=self.term_a,
            progress_summary="Summary",
            report_comment="Comment",
        )
        response = self.client_a.post(
            "/api/reports/generate/", {"student": self.student_a.id, "term": self.term_a.id}
        )
        self.assertEqual(response.status_code, 200)
        mock_generate.assert_called_once()

    @patch("reporting.views.generate_report")
    def test_generate_404s_for_another_schools_student_id(self, mock_generate):
        # The critical regression test: guessing a valid student ID that
        # belongs to a different school must 404, not generate a report
        # for it, and must not leak whether the ID exists at all.
        response = self.client_a.post(
            "/api/reports/generate/", {"student": self.student_b.id, "term": self.term_a.id}
        )
        self.assertEqual(response.status_code, 404)
        mock_generate.assert_not_called()

    @patch("reporting.views.generate_report")
    def test_generate_404s_for_another_schools_term_id(self, mock_generate):
        response = self.client_a.post(
            "/api/reports/generate/", {"student": self.student_a.id, "term": self.term_b.id}
        )
        self.assertEqual(response.status_code, 404)
        mock_generate.assert_not_called()

    @patch("reporting.views.generate_report")
    def test_generate_404s_when_both_ids_belong_to_other_school(self, mock_generate):
        response = self.client_a.post(
            "/api/reports/generate/", {"student": self.student_b.id, "term": self.term_b.id}
        )
        self.assertEqual(response.status_code, 404)
        mock_generate.assert_not_called()

    @patch("reporting.views.generate_report")
    def test_generate_404s_for_nonexistent_ids(self, mock_generate):
        response = self.client_a.post(
            "/api/reports/generate/", {"student": 999999, "term": 999999}
        )
        self.assertEqual(response.status_code, 404)
        mock_generate.assert_not_called()

    def test_generate_returns_503_when_api_key_missing(self):
        with patch(
            "reporting.views.generate_report", side_effect=RuntimeError("GEMINI_API_KEY is not set.")
        ):
            response = self.client_a.post(
                "/api/reports/generate/", {"student": self.student_a.id, "term": self.term_a.id}
            )
        self.assertEqual(response.status_code, 503)

    def test_generate_requires_authentication(self):
        from rest_framework.test import APIClient

        response = APIClient().post(
            "/api/reports/generate/", {"student": self.student_a.id, "term": self.term_a.id}
        )
        self.assertEqual(response.status_code, 401)
