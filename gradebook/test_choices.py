"""Subject choices: electives, IB levels and CBC pathways."""
from accounts.tests import SchoolScopedAPITestCase
from students.models import SchoolClass, Student, YearGroup

from .models import Grade, StudentSubject, Subject, SubjectReport, Term
from .systems import term_summary


class SubjectChoiceTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Grade 10")
        self.klass = SchoolClass.objects.create(year_group=year, name="10 East")
        self.other_class = SchoolClass.objects.create(year_group=year, name="10 West")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.english = Subject.objects.create(school=self.school_a, name="English")
        self.physics = Subject.objects.create(school=self.school_a, name="Physics", is_elective=True)
        self.history = Subject.objects.create(school=self.school_a, name="History", is_elective=True)
        self.ann = Student.objects.create(school=self.school_a, school_class=self.klass, first_name="Ann", last_name="A")
        self.ben = Student.objects.create(school=self.school_a, school_class=self.klass, first_name="Ben", last_name="B")
        self.assign(self.user_a, self.klass, None)

    def save(self, client, rows):
        return client.post("/api/subject-choices/", {"school_class": self.klass.id, "students": rows}, format="json")

    def test_class_teacher_sets_electives_levels_and_pathways(self):
        self.school_a.education_system = "cbc"
        self.school_a.save()
        response = self.save(self.client_a, [
            {"student": self.ann.id, "pathway": "STEM", "subjects": [{"subject": self.physics.id, "level": ""}]},
            {"student": self.ben.id, "pathway": "Social Sciences", "subjects": [{"subject": self.history.id}]},
        ])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["pathways"], ["STEM", "Social Sciences", "Arts and Sports Science"])
        self.ann.refresh_from_db()
        self.assertEqual(self.ann.pathway, "STEM")
        self.assertEqual(list(StudentSubject.objects.filter(student=self.ann).values_list("subject__name", flat=True)),
                         ["Physics"])
        # Saving again replaces the choices.
        self.save(self.client_a, [{"student": self.ann.id, "pathway": "STEM", "subjects": []}])
        self.assertFalse(StudentSubject.objects.filter(student=self.ann).exists())

    def test_bad_input_and_access_are_refused(self):
        self.assertEqual(self.save(self.client_a, [{"student": self.ann.id, "pathway": "Astrology", "subjects": []}]).status_code, 400)
        self.assertEqual(self.save(self.client_a, [{"student": self.ann.id, "subjects": [{"subject": self.physics.id, "level": "XL"}]}]).status_code, 400)
        outsider = Student.objects.create(school=self.school_a, school_class=self.other_class, first_name="C", last_name="C")
        self.assertEqual(self.save(self.client_a, [{"student": outsider.id, "subjects": []}]).status_code, 400)
        response = self.client_a.get("/api/subject-choices/", {"school_class": self.other_class.id})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client_b.get("/api/subject-choices/", {"school_class": self.klass.id}).status_code, 404)

    def grade(self, student, subject):
        return self.admin.post("/api/grades/", {"student": student.id, "subject": subject.id, "term": self.term.id,
                                                "score": 70})

    def test_marks_only_in_subjects_the_student_takes(self):
        StudentSubject.objects.create(student=self.ann, subject=self.physics)
        self.assertEqual(self.grade(self.ann, self.english).status_code, 201)   # core: everyone
        self.assertEqual(self.grade(self.ann, self.physics).status_code, 201)   # chosen elective
        refused = self.grade(self.ben, self.physics)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("doesn't take Physics", str(refused.data))

    def test_subject_comments_list_only_students_taking_an_elective(self):
        StudentSubject.objects.create(student=self.ann, subject=self.physics)
        names = [r["name"] for r in self.admin.get("/api/subject-reports/", {
            "term": self.term.id, "subject": self.physics.id, "school_class": self.klass.id}).data["students"]]
        self.assertEqual(names, ["Ann A"])

    def test_ib_levels_show_in_results(self):
        self.school_a.education_system, self.school_a.grading_scale = "ib", "ib"
        self.school_a.save()
        StudentSubject.objects.create(student=self.ann, subject=self.physics, level="HL")
        Grade.objects.create(student=self.ann, subject=self.physics, term=self.term, score=75)
        SubjectReport.objects.create(student=self.ann, subject=self.english, term=self.term, comment="x")
        rows = {r["subject"]: r["subject_level"] for r in term_summary(self.ann, self.term)["subjects"]}
        self.assertEqual(rows, {"English": "", "Physics": "HL"})
        listed = self.admin.get(f"/api/students/{self.ann.id}/").data
        self.assertEqual(listed["subject_choices"], [{"subject": self.physics.id, "level": "HL"}])
