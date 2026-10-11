"""
Comparisons on the existing charts follow the same rule as the newer ones: an average of another group (a class,
the year group, the school) is only shown with at least MIN_COMPARE_STUDENTS (5) students behind it. A group's own
figures are always shown.
"""
from datetime import date

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Grade, Subject, Term
from reporting.analytics import MIN_COMPARE_STUDENTS
from students.models import SchoolClass, Student, YearGroup


class CompareMinimumTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(MIN_COMPARE_STUDENTS, 5)
        self.admin = self.authed_client(self.admin_a)
        self.term = Term.objects.create(school=self.school_a, name="T1", start_date=date(2026, 1, 5))
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.y7 = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.big = SchoolClass.objects.create(year_group=self.y7, name="7A")    # 5 students: enough
        self.small = SchoolClass.objects.create(year_group=self.y7, name="7B")  # 2 students: too few
        self.y8 = YearGroup.objects.create(school=self.school_a, name="Year 8")
        self.tiny = SchoolClass.objects.create(year_group=self.y8, name="8A")   # 3 students, the whole year group
        self.big_kids = [self.kid(self.big, 50 + i * 10) for i in range(5)]       # 50..90, mean 70
        self.small_kids = [self.kid(self.small, 40), self.kid(self.small, 60)]   # mean 50
        self.tiny_kids = [self.kid(self.tiny, 80) for _ in range(3)]

    def kid(self, klass, score):
        s = Student.objects.create(school=self.school_a, first_name="S", last_name=str(score), school_class=klass)
        Grade.objects.create(student=s, subject=self.maths, term=self.term, score=score)
        return s

    def perf(self, **params):
        return self.admin.get("/api/analytics/performance/", params).data

    def test_student_view(self):
        big = self.perf(scope="student", id=self.big_kids[0].id)
        self.assertEqual(big["trend"][0]["class"], 70.0)          # 5 classmates with marks
        self.assertEqual(big["trend"][0]["year_group"], 64.3)     # 7 in Year 7: (350 + 40 + 60) / 7
        self.assertEqual(big["subjects"][0]["class"], 70.0)
        small = self.perf(scope="student", id=self.small_kids[0].id)
        self.assertIsNone(small["trend"][0]["class"])             # a class of 2: left out
        self.assertIsNone(small["subjects"][0]["class"])
        self.assertEqual(small["trend"][0]["year_group"], 64.3)   # the year group still has 7
        tiny = self.perf(scope="student", id=self.tiny_kids[0].id)
        self.assertEqual((tiny["trend"][0]["class"], tiny["trend"][0]["year_group"]), (None, None))
        self.assertEqual(tiny["trend"][0]["student"], 80.0)       # their own figures stay

    def test_class_view_keeps_its_own_figures(self):
        small = self.perf(scope="class", id=self.small.id)
        self.assertEqual(small["trend"][0]["class"], 50.0)        # the class being looked at: always shown
        self.assertEqual(small["trend"][0]["year_group"], 64.3)
        self.assertEqual(small["trend"][0]["school"], 69.0)       # 10 students: (450 + 240) / 10
        tiny = self.perf(scope="class", id=self.tiny.id)
        self.assertEqual(tiny["trend"][0]["class"], 80.0)
        self.assertIsNone(tiny["trend"][0]["year_group"])         # Year 8 is 3 students
        self.assertIsNone(tiny["subjects"][0]["year_group"])

    def test_year_group_view_leaves_out_small_classes(self):
        data = self.perf(scope="year_group", id=self.y7.id)
        point = data["trend"][0]
        self.assertEqual(point[f"class_{self.big.id}"], 70.0)
        self.assertIsNone(point[f"class_{self.small.id}"])
        groups = {g["name"]: g["average"] for g in data["groups"]}
        self.assertEqual(groups, {"7A": 70.0, "7B": None})
        self.assertEqual(point["year_group"], 64.3)               # its own figure

    def test_school_view_leaves_out_small_year_groups(self):
        groups = {g["name"]: g["average"] for g in self.perf(scope="school")["groups"]}
        self.assertEqual(groups, {"Year 7": 64.3, "Year 8": None})

    def test_staff_profile(self):
        big = self.admin.get(f"/api/students/{self.big_kids[0].id}/profile/").data["performance"][0]
        self.assertEqual((big["class"], big["year_group"]), (70.0, 64.3))
        small = self.admin.get(f"/api/students/{self.small_kids[0].id}/profile/").data["performance"][0]
        self.assertEqual((small["class"], small["year_group"]), (None, 64.3))

    def test_teacher_home_compares_only_with_big_enough_classes(self):
        self.assign(self.user_a, self.small, self.maths)
        self.assign(self.user_a, self.tiny, self.maths)
        data = self.authed_client(self.user_a).get("/api/teacher-home/performance/").data
        rows = {r["name"]: r for r in data["classes"]}
        # 7B (50) against 7A (70): 2nd of 2. Its own average is shown though it has 2 students.
        self.assertEqual((rows["7B"]["average"], rows["7B"]["rank"], rows["7B"]["of"]), (50.0, 2, 2))
        self.assertEqual(rows["7B"]["year_average"], 64.3)
        # 8A is its whole year group of 3: no year comparison.
        self.assertEqual((rows["8A"]["average"], rows["8A"]["year_average"]), (80.0, None))
