"""Schools running two systems: a section of year groups with its own curriculum and grading."""
from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Grade, Subject, Term
from gradebook.systems import term_summary
from reporting.models import StudentReport
from reporting.services import _build_prompt as report_prompt

from .models import SchoolClass, Student, YearGroup
from .presets import student_section


class SectionTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.school_a.education_system, self.school_a.grading_scale = "cbc", "cbc4"
        self.school_a.save()
        self.admin = self.authed_client(self.admin_a)
        grade7 = YearGroup.objects.create(school=self.school_a, name="Grade 7", order=0, is_final=True)
        self.c7 = SchoolClass.objects.create(year_group=grade7, name="7 East")
        self.term = Term.objects.create(school=self.school_a, name="Term 1", start_date="2026-01-05",
                                        end_date="2026-04-01")
        self.maths = Subject.objects.create(school=self.school_a, name="Mathematics")

    def add_section(self, **overrides):
        body = {"education_system": "british", "grading_scale": "igcse9",
                "year_groups": [{"name": "Year 10", "classes": ["10A"]}, {"name": "Year 11", "classes": ["11A"]}],
                "subjects": ["Mathematics", "Chemistry"]}
        body.update(overrides)
        return self.admin.post("/api/setup/add-section/", body, format="json")

    def student(self, klass, score=85):
        s = Student.objects.create(school=self.school_a, school_class=klass, first_name="Ada", last_name="L")
        Grade.objects.create(student=s, subject=self.maths, term=self.term, score=score)
        return s

    def test_adding_a_section_creates_its_year_groups_after_the_schools_own(self):
        response = self.add_section()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["created"], {"year_groups": 2, "classes": 2, "subjects": 1})
        groups = list(YearGroup.objects.filter(school=self.school_a).order_by("order")
                      .values_list("name", "order", "is_final", "education_system", "grading_scale"))
        self.assertEqual(groups, [("Grade 7", 0, True, "", ""), ("Year 10", 1, False, "british", "igcse9"),
                                  ("Year 11", 2, True, "british", "igcse9")])

    def test_section_names_must_be_new_and_only_admins_can_add(self):
        self.assertEqual(self.add_section(year_groups=[{"name": "Grade 7", "classes": ["7B"]}]).status_code, 400)
        self.assertEqual(self.add_section(education_system="klingon").status_code, 400)
        response = self.client_a.post("/api/setup/add-section/", {"education_system": "british"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(YearGroup.objects.filter(school=self.school_b).exists())

    def test_results_follow_the_students_section(self):
        self.add_section()
        cbc = self.student(self.c7)
        igcse = self.student(SchoolClass.objects.get(name="10A"))
        self.assertEqual(student_section(igcse), ("british", "igcse9"))
        s = term_summary(cbc, self.term)
        self.assertEqual((s["system"], s["scale"], s["subjects"][0]["level"]), ("cbc", "cbc4", "EE"))
        s = term_summary(igcse, self.term)
        self.assertEqual((s["system"], s["scale"], s["subject_word"]), ("british", "igcse9", "Subject"))
        self.assertEqual(s["subjects"][0]["level"], "8")

    def test_ai_writing_and_report_extras_follow_the_section(self):
        self.add_section()
        igcse = self.student(SchoolClass.objects.get(name="10A"))
        text = report_prompt(igcse, self.term, "formal")
        self.assertNotIn("core competencies", text)
        self.assertIn("IGCSE", text)
        self.assertIn("core competencies", report_prompt(self.student(self.c7), self.term, "formal"))
        report = StudentReport.objects.create(student=igcse, term=self.term, progress_summary="s")
        data = self.admin.get(f"/api/reports/{report.id}/").data
        self.assertEqual(data["extra_groups"], [])
        # CBC competency ratings don't belong on an IGCSE student's report.
        response = self.admin.patch(f"/api/reports/{report.id}/",
                                    {"extra": {"competencies": {"Communication and collaboration": "EE"}}},
                                    format="json")
        self.assertEqual((response.status_code, response.data["extra"]), (200, {}))

    def test_subject_report_fields_and_choices_follow_the_section(self):
        self.add_section(education_system="ib", grading_scale="ib", year_groups=[{"name": "MYP 4", "classes": ["M4"]}])
        myp = SchoolClass.objects.get(name="M4")
        response = self.admin.get("/api/subject-reports/", {"term": self.term.id, "subject": self.maths.id,
                                                            "school_class": myp.id})
        self.assertIn("criteria", response.data["fields"])
        choices = self.admin.get("/api/subject-choices/", {"school_class": myp.id}).data
        self.assertEqual((choices["system"], choices["pathways"]), ("ib", []))
        self.assertEqual(self.admin.get("/api/subject-choices/", {"school_class": self.c7.id}).data["system"], "cbc")

    def test_report_card_pdf_for_a_section(self):
        self.add_section()
        igcse = self.student(SchoolClass.objects.get(name="10A"))
        StudentReport.objects.create(student=igcse, term=self.term, progress_summary="s", status="finalized",
                                     report_comment="Well done.")
        response = self.admin.get("/api/exports/reports/", {"school_class": igcse.school_class_id,
                                                            "term": self.term.id})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_year_groups_can_be_moved_into_a_section(self):
        grade7 = self.c7.year_group
        url = f"/api/year-groups/{grade7.id}/"
        self.assertEqual(self.admin.patch(url, {"education_system": "844", "grading_scale": "kcse"},
                                          format="json").status_code, 200)
        self.assertEqual(term_summary(self.student(SchoolClass.objects.get(pk=self.c7.pk)), self.term)["system"], "844")
        self.assertEqual(self.admin.patch(url, {"grading_scale": "nope"}, format="json").status_code, 400)
