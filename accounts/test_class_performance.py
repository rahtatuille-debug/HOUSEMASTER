"""
Teacher dashboard (owner's request, 2026-10-08): each of the teacher's
classes with its average and position in its year group, overall and in each
subject. Other classes are counted, never named.
"""
from gradebook.models import Grade

from .models import StaffRole
from .test_roles import RoleFixture

URL = "/api/teacher-home/performance/"


class ClassPerformanceTests(RoleFixture):
    def setUp(self):
        super().setUp()
        # Every pupil already has 60 in maths (RoleFixture). Ben's class (2 West) does better in English.
        for student, score in ((self.amina, 50), (self.ben, 80)):
            Grade.objects.create(student=student, subject=self.english, term=self.term, score=score)

    def test_a_teacher_sees_their_class_ranked_in_its_year_group(self):
        data = self.client_a.get(URL).data
        self.assertEqual(data["term_name"], "T1")
        (row,) = data["classes"]  # user_a teaches 2 East only
        self.assertEqual((row["name"], row["average"], row["rank"], row["of"]), ("2 East", 55.0, 2, 2))
        subjects = {s["subject"]: s for s in row["subjects"]}
        self.assertEqual((subjects["Maths"]["rank"], subjects["Maths"]["of"], subjects["Maths"]["teaches"]), (1, 2, True))
        self.assertEqual((subjects["English"]["rank"], subjects["English"]["year_average"]), (2, 65.0))
        self.assertFalse(subjects["English"]["teaches"])
        self.assertNotIn("2 West", str(data))  # other classes are never named

    def test_a_head_of_year_sees_every_class_in_their_year(self):
        _, hoy = self.staff("hoy@alpha.test", "teacher", ("head_of_year", {"year_group": self.form2}))
        names = [(c["name"], c["rank"]) for c in hoy.get(URL).data["classes"]]
        self.assertEqual(names, [("2 East", 2), ("2 West", 1)])

    def test_a_class_alone_in_its_year_is_first_of_one(self):
        maths3 = self.maths_3e[1]
        (row,) = maths3.get(URL).data["classes"]
        self.assertEqual((row["name"], row["rank"], row["of"]), ("3 East", 1, 1))

    def test_no_marks_yet(self):
        Grade.objects.all().delete()
        self.assertEqual(self.client_a.get(URL).data["classes"], [])
        _, lead = self.staff("lead@alpha.test", "teacher", StaffRole.Role.LEADERSHIP)
        self.assertEqual(lead.get(URL).status_code, 200)
