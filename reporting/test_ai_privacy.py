"""
F-08: no child's (or parent's) identity ever leaves the system in an AI
prompt. The model sees a placeholder, grades and attendance counts only;
the real first name is put back in locally afterwards.
"""
import os
from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache

from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Subject, Term
from guardians.models import Guardian
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

NOTE = "Collected early by aunt, doctor appointment"


def capturing_client(reply):
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text=reply)
    return MagicMock(return_value=client), client


def sent_prompt(client):
    return client.models.generate_content.call_args.kwargs["contents"]


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-not-real"})
class ReportPromptPrivacyTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.make_admin(self.user_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        school_class = SchoolClass.objects.create(year_group=year, name="7 Kilimanjaro")
        self.term = Term.objects.create(school=self.school_a, name="Term 1", start_date=date(2026, 1, 5),
                                        end_date=date(2026, 4, 3))
        self.student = Student.objects.create(
            school=self.school_a, first_name="Wanjiru", last_name="Kiprotich", external_id="ADM-99812",
            house="Simba House", school_class=school_class, medical_notes="Asthma inhaler",
        )
        maths = Subject.objects.create(school=self.school_a, name="Mathematics")
        Grade.objects.create(student=self.student, subject=maths, term=self.term, score=81, max_score=100)
        AttendanceRecord.objects.create(student=self.student, date=date(2026, 2, 2), status="late", notes=NOTE)
        AttendanceRecord.objects.create(student=self.student, date=date(2026, 2, 3), status="present")
        parent = User.objects.create_user(username="p@example.org", email="parent.kiprotich@example.org",
                                          password="pass1234")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Josephine Chebet").students.add(
            self.student)

    def generate(self, reply):
        factory, client = capturing_client(reply)
        with patch("google.genai.Client", factory):
            response = self.client_a.post("/api/reports/generate/",
                                          {"student": self.student.id, "term": self.term.id}, format="json")
        return response, client

    def test_prompt_contains_no_identifying_details(self):
        response, client = self.generate("SUMMARY:\nSteady.\nCOMMENT:\n[STUDENT] did well.")
        self.assertEqual(response.status_code, 200, response.data)
        prompt = sent_prompt(client)
        for secret in ["Wanjiru", "Kiprotich", "ADM-99812", "Josephine", "Chebet", "parent.kiprotich",
                       "Simba", "Kilimanjaro", NOTE, "Asthma", "Alpha Academy"]:
            self.assertNotIn(secret, prompt)
        # What the model does need is still there.
        self.assertIn("[STUDENT]", prompt)
        self.assertIn("Mathematics: 81", prompt)
        self.assertIn("1 late", prompt)

    def test_real_first_name_is_put_back_locally(self):
        response, _ = self.generate("SUMMARY:\n[STUDENT] is steady.\nCOMMENT:\n[STUDENT] did well in Mathematics.")
        report = StudentReport.objects.get(student=self.student)
        self.assertEqual(report.report_comment, "Wanjiru did well in Mathematics.")
        self.assertEqual(report.progress_summary, "Wanjiru is steady.")

    def test_placeholder_variants_are_handled(self):
        from reporting.services import substitute_name

        self.assertEqual(substitute_name("[Student]'s work and [ STUDENT ] again, STUDENT too", "Wanjiru"),
                         "Wanjiru's work and Wanjiru again, Wanjiru too")
        # The ordinary word is left alone.
        self.assertEqual(substitute_name("A strong student this term.", "Wanjiru"), "A strong student this term.")

    def test_no_first_name_falls_back_to_the_student(self):
        from reporting.services import substitute_name

        self.assertEqual(substitute_name("[STUDENT] improved.", ""), "The student improved.")
        self.assertEqual(substitute_name("Well done, [STUDENT].", "  "), "Well done, the student.")


@patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-not-real"})
class AnnouncementPromptPrivacyTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.make_admin(self.user_a)
        Student.objects.create(school=self.school_a, first_name="Wanjiru", last_name="Kiprotich")
        parent = User.objects.create_user(username="p2@example.org", email="p2@example.org", password="pass1234")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Josephine Chebet")

    def test_names_and_emails_in_the_brief_are_masked_and_restored(self):
        factory, client = capturing_client(
            "TITLE:\nCongratulations [PERSON 1]\nBODY:\nWell done [PERSON 1]. Questions to [EMAIL 1]."
        )
        brief = ("Congratulate Wanjiru Kiprotich on winning the county maths contest; "
                 "thank Josephine Chebet for the transport; questions to office@alpha.example.org")
        with patch("google.genai.Client", factory):
            response = self.client_a.post("/api/announcements/generate-text/",
                                          {"summary": brief, "audience": "all_parents"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        prompt = sent_prompt(client)
        for secret in ["Wanjiru", "Kiprotich", "Josephine", "Chebet", "office@alpha.example.org", "Alpha Academy"]:
            self.assertNotIn(secret, prompt)
        self.assertEqual(response.data["title"], "Congratulations Wanjiru Kiprotich")
        self.assertIn("Questions to office@alpha.example.org.", response.data["body"])
