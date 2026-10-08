"""
All classes (owner's request, 2026-10-08): any teacher sees every class's
average and position in its year group, and each class's subject averages.
Class figures only: never a student, and nothing built from fewer than three
students' marks.
"""
from gradebook.models import Grade, Subject
from students.models import SchoolClass, Student, YearGroup

from .test_roles import RoleFixture

URL = "/api/teacher-home/all-classes/"


class AllClassesTests(RoleFixture):
    def setUp(self):
        super().setUp()
        Grade.objects.all().delete()
        # 2 East: 50, 60, 70 in maths; 2 West: 80, 80, 80; 3 East: only two students marked.
        for klass, scores in ((self.c2e, (50, 60, 70)), (self.c2w, (80, 80, 80)), (self.c3e, (90, 90))):
            for n, score in enumerate(scores):
                student = Student.objects.create(school=self.school_a, first_name=f"Pupil{klass.id}{n}",
                                                 last_name="Secretname", school_class=klass)
                Grade.objects.create(student=student, subject=self.maths, term=self.term, score=score)

    def test_a_teacher_sees_every_class_with_its_average_and_position(self):
        data = self.client_a.get(URL).data  # user_a teaches 2 East only
        self.assertEqual(data["term_name"], "T1")
        form2 = next(y for y in data["year_groups"] if y["name"] == "Form 2")
        rows = {c["name"]: c for c in form2["classes"]}
        self.assertEqual((rows["2 West"]["average"], rows["2 West"]["rank"], rows["2 West"]["of"]), (80.0, 1, 2))
        self.assertEqual((rows["2 East"]["average"], rows["2 East"]["rank"], rows["2 East"]["mine"]), (60.0, 2, True))
        self.assertFalse(rows["2 West"]["mine"])
        self.assertEqual(rows["2 West"]["subjects"], {"Maths": 80.0})
        self.assertEqual(form2["average"], 70.0)

    def test_never_a_student(self):
        text = str(self.client_a.get(URL).data)
        for word in ("Secretname", "Pupil", "Amina", "Ben"):
            self.assertNotIn(word, text)

    def test_a_class_with_fewer_than_three_marked_students_shows_no_average(self):
        form3 = next(y for y in self.client_a.get(URL).data["year_groups"] if y["name"] == "Form 3")
        (row,) = form3["classes"]
        self.assertEqual((row["average"], row["rank"], row["subjects"]["Maths"]), (None, None, None))

    def test_only_this_school(self):
        other = YearGroup.objects.create(school=self.school_b, name="Other year")
        klass = SchoolClass.objects.create(year_group=other, name="Z1")
        subject = Subject.objects.create(school=self.school_b, name="Maths")
        for n in range(3):
            s = Student.objects.create(school=self.school_b, first_name=f"Z{n}", last_name="B", school_class=klass)
            Grade.objects.create(student=s, subject=subject, term=self.term, score=40)
        self.assertNotIn("Z1", str(self.client_a.get(URL).data))

    def test_no_marks_yet_and_governors(self):
        Grade.objects.all().delete()
        self.assertEqual(self.client_a.get(URL).data["year_groups"], [])
        _, gov = self.staff("gov@alpha.test", "governor")
        self.assertEqual(gov.get(URL).status_code, 403)
