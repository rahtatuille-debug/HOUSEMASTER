"""
F-11: a report can't reach parents with a blank comment.

An AI answer that can't be split into a summary and a comment is refused
(502, nothing saved) instead of being saved with an empty comment, and a
report with a blank comment or summary can't be submitted or finalized,
one at a time or for a whole class. Parents never see a blank report, even
one finalized before this rule existed.
"""
import os
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Term
from guardians.models import Guardian
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup



def client_replying(text):
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text=text)
    return MagicMock(return_value=client)


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-not-real"})
class BlankReportTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.assign(self.user_a, self.klass, None)
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.student = Student.objects.create(school=self.school_a, first_name="Amina", last_name="Otieno",
                                              school_class=self.klass)

    def report(self, comment="Well done.", summary="Steady progress.", status="draft", student=None):
        return StudentReport.objects.create(student=student or self.student, term=self.term, report_comment=comment,
                                            progress_summary=summary, tone_used="formal", status=status)

    def generate(self, reply):
        with patch("google.genai.Client", client_replying(reply)):
            return self.client_a.post("/api/reports/generate/", {"student": self.student.id, "term": self.term.id},
                                      format="json")

    # --- the AI answer ---------------------------------------------------

    def test_answer_without_the_two_parts_is_refused_and_nothing_is_saved(self):
        response = self.generate("Amina has worked hard this term.")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(StudentReport.objects.exists())

    def test_answer_with_an_empty_comment_is_refused(self):
        self.assertEqual(self.generate("SUMMARY:\nFine.\nCOMMENT:\n   ").status_code, 502)
        self.assertEqual(self.generate("SUMMARY:\n\nCOMMENT:\nGood work.").status_code, 502)
        self.assertFalse(StudentReport.objects.exists())

    def test_unusable_answer_leaves_an_existing_draft_alone(self):
        self.report(comment="Teacher's own words.")
        self.generate("no headers at all")
        self.assertEqual(StudentReport.objects.get().report_comment, "Teacher's own words.")

    def test_good_answer_still_works(self):
        response = self.generate("SUMMARY:\nSteady.\nCOMMENT:\n[STUDENT] did well.")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["report_comment"], "Amina did well.")

    # --- submitting and finalizing ---------------------------------------

    def test_blank_or_whitespace_comment_cannot_be_submitted(self):
        for comment in ["", "   \n\t "]:
            StudentReport.objects.all().delete()
            report = self.report(comment=comment)
            response = self.client_a.post(f"/api/reports/{report.id}/submit/")
            self.assertEqual(response.status_code, 400, comment)
            self.assertEqual(StudentReport.objects.get().status, "draft")

    def test_blank_summary_cannot_be_submitted(self):
        report = self.report(summary=" ")
        self.assertEqual(self.client_a.post(f"/api/reports/{report.id}/submit/").status_code, 400)

    def test_blank_comment_cannot_be_finalized(self):
        report = self.report(comment="", status="submitted")
        self.assertEqual(self.admin.post(f"/api/reports/{report.id}/finalize/").status_code, 400)
        self.assertEqual(StudentReport.objects.get().status, "submitted")

    def test_whole_class_submit_and_finalize_skip_blank_reports(self):
        other = Student.objects.create(school=self.school_a, first_name="Brian", last_name="Kamau",
                                       school_class=self.klass)
        good = self.report()
        blank = self.report(comment=" ", student=other)
        body = {"school_class": self.klass.id, "term": self.term.id}
        submitted = self.client_a.post("/api/reports/submit-class/", body, format="json")
        self.assertEqual(submitted.data["count"], 1)
        self.assertEqual(submitted.data["blank"], 1)
        blank.refresh_from_db()
        self.assertEqual(blank.status, "draft")
        StudentReport.objects.filter(pk=blank.pk).update(status="submitted")
        finalized = self.admin.post("/api/reports/finalize-class/", body, format="json")
        self.assertEqual(finalized.data["count"], 1)
        self.assertEqual(finalized.data["blank"], 1)
        good.refresh_from_db()
        blank.refresh_from_db()
        self.assertEqual((good.status, blank.status), ("finalized", "submitted"))

    # --- parents ---------------------------------------------------------

    def test_parents_never_see_a_blank_report_even_an_old_finalized_one(self):
        self.report(comment="  ", status="finalized")  # finalized before this rule existed
        parent = User.objects.create_user(username="grace", email="grace@example.org", password="pass1234")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Grace").students.add(self.student)
        client = self.authed_client(parent)
        base = f"/api/guardian-students/{self.student.id}"
        self.assertEqual(client.get(f"{base}/reports/").data, [])
        self.assertEqual(client.get(f"{base}/term-summary/", {"term": self.term.id}).status_code, 404)
        self.assertEqual(client.get(f"{base}/report-card/", {"term": self.term.id}).status_code, 404)
