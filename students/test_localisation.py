"""Each school's own words, AI writing guidance and country (privacy law, formats)."""
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from communications.services import _build_prompt as announcement_prompt
from gradebook.models import Grade, Subject, Term
from reporting.services import _build_prompt as report_prompt

from .models import School, SchoolClass, Student, YearGroup
from .presets import SYSTEMS, VOCAB


class VocabularyTests(SchoolScopedAPITestCase):
    def school_words(self):
        return self.authed_client(self.admin_a).get("/api/me/").data["school"]["vocab"]

    def test_each_system_uses_its_own_words(self):
        self.assertEqual(self.school_words()["class"], "Class")  # no system chosen yet
        expected = {"cbc": ("Grade", "Stream", "Learning area", "Term"), "844": ("Form", "Stream", "Subject", "Term"),
                    "british": ("Year", "Form", "Subject", "Term"), "american": ("Grade", "Homeroom", "Course", "Semester"),
                    "ib": ("Year group", "Class", "Subject", "Term")}
        for system, words in expected.items():
            self.school_a.education_system = system
            self.school_a.save()
            got = self.school_words()
            self.assertEqual((got["year_group"], got["class"], got["subject"], got["term"]), words, system)

    def test_every_system_has_every_word(self):
        self.assertEqual(set(VOCAB), set(SYSTEMS))
        keys = set(VOCAB["cbc"])
        self.assertTrue(all(set(v) == keys for v in VOCAB.values()))

    def test_exports_use_the_schools_words(self):
        import openpyxl
        from io import BytesIO
        self.school_a.education_system = "american"
        self.school_a.save()
        year = YearGroup.objects.create(school=self.school_a, name="Grade 9")
        klass = SchoolClass.objects.create(year_group=year, name="Room 12")
        Student.objects.create(school=self.school_a, school_class=klass, first_name="Ann", last_name="Lee")
        response = self.authed_client(self.admin_a).get("/api/exports/class-list/", {"school_class": klass.id})
        header = [c.value for c in openpyxl.load_workbook(BytesIO(response.content)).active[1]]
        self.assertEqual(header[0], "Student ID")


class CountryTests(SchoolScopedAPITestCase):
    def test_sign_up_records_the_country_and_me_sends_its_privacy_law(self):
        response = APIClient().post("/api/schools/register/", {
            "school_name": "Oakfield", "name": "Sam Hill", "email": "sam@oakfield.test",
            "password": "a-long-Password-123", "accept_privacy": True, "country": "gb"})
        self.assertEqual(response.status_code, 201)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        country = client.get("/api/me/").data["school"]["country"]
        self.assertEqual((country["code"], country["locale"]), ("gb", "en-GB"))
        self.assertIn("UK GDPR", country["law"])
        self.assertIn("ICO", country["regulator"])

    def test_schools_default_to_kenya_and_unknown_countries_are_refused(self):
        self.assertIn("Data Protection Act, 2019", self.authed_client(self.admin_a).get("/api/me/").data["school"]["country"]["law"])
        bad = APIClient().post("/api/schools/register/", {
            "school_name": "X", "name": "Sam Hill", "email": "x@x.test", "password": "a-long-Password-123",
            "accept_privacy": True, "country": "mars"})
        self.assertEqual(bad.status_code, 400)

    def test_invite_preview_carries_the_country(self):
        from accounts.models import Invite
        self.school_a.country = "us"
        self.school_a.save()
        invite = Invite.objects.create(school=self.school_a, email="n@alpha.test", name="N", invited_by=self.admin_a)
        preview = APIClient().get(f"/api/invites/preview/{invite.token}/").data
        self.assertIn("FERPA", preview["country"]["law"])


class AIWritingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.term = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.student = Student.objects.create(school=self.school_a, first_name="Amina", last_name="Otieno")
        Grade.objects.create(student=self.student, subject=Subject.objects.create(school=self.school_a, name="Maths"),
                             term=self.term, score=72)

    def prompt(self, system, country="ke", scale="cbc4"):
        self.school_a.education_system, self.school_a.country, self.school_a.grading_scale = system, country, scale
        self.school_a.save()
        self.student.school = School.objects.get(pk=self.school_a.pk)
        return report_prompt(self.student, self.term, "formal")

    def test_cbc_reports_use_levels_competencies_and_no_ranking(self):
        text = self.prompt("cbc")
        self.assertIn("Maths: 72.00/100.00 (72%, ME)", text)
        self.assertIn("core competencies", text)
        self.assertIn("Never rank", text)
        self.assertIn('a subject is a "learning area"', text)

    def test_other_systems_get_their_own_guidance_and_spelling(self):
        self.assertIn("KCSE", self.prompt("844", scale="kcse"))
        self.assertIn("learner profile", self.prompt("ib", scale="ib"))
        american = self.prompt("american", country="us", scale="american")
        self.assertIn("American English", american)
        self.assertIn("Semester: Term 1 2026", american)
        self.assertIn("(72%, C)", american)
        self.assertIn("British English", self.prompt("british", country="gb", scale="igcse"))

    def test_announcements_use_the_schools_words(self):
        self.school_a.education_system = "844"
        text = announcement_prompt(school=self.school_a, summary="Form 2 trip", audience_label="All parents")
        self.assertIn('a year group is a "form"', text)
        self.assertIn("KCSE", text)
