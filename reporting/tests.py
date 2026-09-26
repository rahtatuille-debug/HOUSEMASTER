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

from django.core.cache import cache
from rest_framework.throttling import ScopedRateThrottle

from students.models import Student
from gradebook.models import Term
from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog

from .models import StudentReport


class StudentReportScopingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.user_a, self.user_b)
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
        # Another school's record is rejected exactly like one that doesn't exist.
        self.assertEqual(response.status_code, 400)


class GenerateActionScopingTests(SchoolScopedAPITestCase):
    """
    This is the highest-priority test class in the whole suite per the
    hardening plan: the `generate` action previously had no scoping at
    all, and it's a custom @action that the generic queryset-filtering
    mixin doesn't automatically protect.
    """

    def setUp(self):
        super().setUp()
        self.make_admin(self.user_a, self.user_b)
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


class ReportApprovalTests(SchoolScopedAPITestCase):
    """Teachers submit reports; only admins finalize them or send them back."""

    def setUp(self):
        super().setUp()
        from gradebook.models import Subject
        from students.models import SchoolClass, YearGroup

        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        school_class = SchoolClass.objects.create(year_group=year, name="7A")
        self.student = Student.objects.create(school=self.school_a, first_name="Ann", last_name="One",
                                              school_class=school_class)
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.assign(self.user_a, school_class, Subject.objects.create(school=self.school_a, name="Maths"))
        self.report = StudentReport.objects.create(
            student=self.student, term=self.term, progress_summary="S", report_comment="C"
        )

    def url(self, action=""):
        return f"/api/reports/{self.report.id}/" + (f"{action}/" if action else "")

    def test_teacher_submits_and_admin_finalizes(self):
        response = self.client_a.post(self.url("submit"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "submitted")
        self.assertIsNotNone(response.data["submitted_by_name"])

        response = self.admin_client_a.post(self.url("finalize"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "finalized")
        actions = set(ActivityLog.objects.values_list("action", flat=True))
        self.assertTrue({"report.submitted", "report.finalized"} <= actions)

    def test_teacher_cannot_finalize(self):
        self.client_a.post(self.url("submit"))
        self.assertEqual(self.client_a.post(self.url("finalize")).status_code, 403)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, "submitted")

    def test_status_cannot_be_changed_by_editing(self):
        response = self.client_a.patch(self.url(), {"status": "finalized", "report_comment": "New"})
        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, "draft")
        self.assertEqual(self.report.report_comment, "New")

    def test_new_report_cannot_be_created_already_finalized(self):
        self.report.delete()
        response = self.client_a.post("/api/reports/", {
            "student": self.student.id, "term": self.term.id, "progress_summary": "S",
            "report_comment": "C", "status": "finalized",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "draft")

    def test_admin_sends_back_with_a_note(self):
        self.client_a.post(self.url("submit"))
        self.assertEqual(self.admin_client_a.post(self.url("send-back")).status_code, 400)  # note required
        response = self.admin_client_a.post(self.url("send-back"), {"note": "Mention her reading"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["review_note"], "Mention her reading")
        self.assertEqual(self.client_a.post(self.url("send-back"), {"note": "x"}).status_code, 403)

    def test_sending_back_a_finalized_report_hides_it_from_parents(self):
        self.admin_client_a.post(self.url("finalize"))
        self.admin_client_a.post(self.url("send-back"), {"note": "Typo"})
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, "draft")
        self.assertIsNone(self.report.finalized_at)

    def test_finalized_report_is_locked(self):
        self.admin_client_a.post(self.url("finalize"))
        self.assertEqual(self.admin_client_a.patch(self.url(), {"report_comment": "X"}).status_code, 400)
        self.assertEqual(self.admin_client_a.delete(self.url()).status_code, 400)

    @patch("reporting.views.generate_report")
    def test_submitted_or_finalized_report_cannot_be_regenerated(self, mock_generate):
        self.client_a.post(self.url("submit"))
        response = self.client_a.post("/api/reports/generate/", {"student": self.student.id,
                                                                 "term": self.term.id})
        self.assertEqual(response.status_code, 400)
        mock_generate.assert_not_called()

    def test_only_drafts_can_be_submitted(self):
        self.client_a.post(self.url("submit"))
        self.assertEqual(self.client_a.post(self.url("submit")).status_code, 400)


class GenerateActionRateLimitTests(SchoolScopedAPITestCase):
    """
    Dedicated, isolated coverage for the rate limit on `generate`.

    Directly patches ScopedRateThrottle.THROTTLE_RATES (a dict) rather than
    using Django's override_settings on REST_FRAMEWORK: DRF binds that dict
    onto the throttle class once, at import time, from api_settings —
    override_settings updates api_settings itself (via DRF's setting_changed
    signal receiver) but does not retroactively rewrite the class attribute
    an already-imported throttle class is holding, so a settings-based
    override here would silently have no effect on the *rate actually used*
    even though it looks like it should. Patching the dict in place is what
    actually reaches the code path that matters.

    Also explicitly cache.clear()s — DRF's throttle counters live in
    Django's cache, which isn't reset between test methods automatically,
    so without this a test could be flaky depending on how many times
    other tests in the suite already hit this endpoint.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        # Admins aren't limited to assigned classes, so generation isn't
        # refused for reasons unrelated to the rate limit.
        self.make_admin(self.user_a)
        self.student = Student.objects.create(school=self.school_a, first_name="Amina", last_name="Otieno")
        self.term = Term.objects.create(school=self.school_a, name="Term 1 2026")

    @patch("reporting.views.generate_report")
    def test_exceeding_the_rate_returns_429(self, mock_generate):
        mock_generate.return_value = StudentReport.objects.create(
            student=self.student, term=self.term, progress_summary="x", report_comment="x"
        )
        payload = {"student": self.student.id, "term": self.term.id}

        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"ai_report_generation": "2/min"}):
            first = self.client_a.post("/api/reports/generate/", payload)
            second = self.client_a.post("/api/reports/generate/", payload)
            third = self.client_a.post("/api/reports/generate/", payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 429)
        self.assertEqual(mock_generate.call_count, 2)  # the throttled request never reached the AI call

    @patch("reporting.views.generate_report")
    def test_rate_limit_is_per_user_not_global(self, mock_generate):
        mock_generate.return_value = StudentReport.objects.create(
            student=self.student, term=self.term, progress_summary="x", report_comment="x"
        )
        payload = {"student": self.student.id, "term": self.term.id}

        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"ai_report_generation": "1/min"}):
            first_user = self.client_a.post("/api/reports/generate/", payload)
            self.assertEqual(first_user.status_code, 200)

            second_user_client = self.authed_client(self.admin_a)
            second_user = second_user_client.post("/api/reports/generate/", payload)
            self.assertEqual(second_user.status_code, 200)  # a different user isn't affected by user_a's limit

    def test_other_report_endpoints_are_not_throttled(self):
        # throttle_scope is a class attribute (shared across every action on
        # this viewset), but get_throttles() only actually engages it for
        # `generate` — plain list/CRUD must be unaffected even at rate 0.
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"ai_report_generation": "0/min"}):
            response = self.client_a.get("/api/reports/")
        self.assertEqual(response.status_code, 200)
