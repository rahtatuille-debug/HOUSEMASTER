"""The sample report card in the setup wizard."""
from io import BytesIO

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Grade, Subject
from reporting.models import StudentReport

from .models import School, Student


class ReportPreviewTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)

    def preview(self, **body):
        return self.admin.post("/api/setup/preview-report/", body, format="json")

    def text(self, response):
        from pypdf import PdfReader

        return " ".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)

    def test_every_system_gets_a_sample_in_its_own_style(self):
        expected = {"cbc": "Core competencies", "844": "Mean grade", "british": "Effort", "ib": "Approaches to learning",
                    "american": "GPA"}
        for system, marker in expected.items():
            response = self.preview(education_system=system)
            self.assertEqual(response.status_code, 200, system)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertIn(marker, self.text(response), system)

    def test_uses_the_wizard_answers_and_saves_nothing(self):
        schools, students, subjects = School.objects.count(), Student.objects.count(), Subject.objects.count()
        response = self.preview(education_system="british", name="Riverside International", country="gb",
                                grading_scale="igcse9", report_tone="concise", subjects=["Physics", "History"],
                                year_groups=[{"name": "Year 10", "classes": ["10 Blue"]}])
        text = self.text(response)
        for part in ("RIVERSIDE INTERNATIONAL", "Olivia Bennett", "Year 10", "10 Blue", "Physics", "History",
                     "A good term."):
            self.assertIn(part, text)
        self.assertEqual((School.objects.count(), Student.objects.count(), Subject.objects.count()),
                         (schools, students, subjects))
        self.assertFalse(Grade.objects.exists() or StudentReport.objects.exists())

    def test_admins_only_and_needs_a_system(self):
        self.assertEqual(self.preview().status_code, 400)
        response = self.client_a.post("/api/setup/preview-report/", {"education_system": "cbc"}, format="json")
        self.assertEqual(response.status_code, 403)
