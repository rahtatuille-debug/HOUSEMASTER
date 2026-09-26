"""Performance analytics: the numbers, and who can see which level."""
from datetime import date

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Grade, Subject, Term
from students.models import SchoolClass, Student, YearGroup


class PerformanceAnalyticsTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        y7 = YearGroup.objects.create(school=self.school_a, name="Year 7")
        y8 = YearGroup.objects.create(school=self.school_a, name="Year 8")
        self.y7 = y7
        self.c7a = SchoolClass.objects.create(year_group=y7, name="7A")
        self.c7b = SchoolClass.objects.create(year_group=y7, name="7B")
        self.c8a = SchoolClass.objects.create(year_group=y8, name="8A")
        self.t1 = Term.objects.create(school=self.school_a, name="T1", start_date=date(2026, 1, 1))
        self.t2 = Term.objects.create(school=self.school_a, name="T2", start_date=date(2026, 5, 1))
        maths = Subject.objects.create(school=self.school_a, name="Maths")
        art = Subject.objects.create(school=self.school_a, name="Art")

        def student(name, klass, marks):
            s = Student.objects.create(school=self.school_a, first_name=name, last_name="X", school_class=klass)
            for term, subject, score in marks:
                Grade.objects.create(student=s, subject=subject, term=term, score=score)
            return s

        # Ann: T1 Maths 80 + Art 60 = 70; T2 Maths 90 = 90.  Ben: T1 Maths 50; T2 Maths 70.
        self.ann = student("Ann", self.c7a, [(self.t1, maths, 80), (self.t1, art, 60), (self.t2, maths, 90)])
        self.ben = student("Ben", self.c7a, [(self.t1, maths, 50), (self.t2, maths, 70)])
        self.cy = student("Cy", self.c7b, [(self.t1, maths, 40), (self.t2, maths, 30)])
        self.dee = student("Dee", self.c8a, [(self.t1, maths, 100), (self.t2, maths, 100)])
        gone = student("Gone", self.c7a, [(self.t1, maths, 0)])
        gone.is_active = False
        gone.save()
        Student.objects.create(school=self.school_b, first_name="Other", last_name="School")
        self.assign(self.user_a, self.c7a, maths)

    def get(self, client=None, **params):
        return (client or self.admin_client_a).get("/api/analytics/performance/", params)

    def test_student(self):
        data = self.get(scope="student", id=self.ann.id, term=self.t1.id).data
        # class T1: Ann 70, Ben 50 -> 60. Year 7 T1: 70, 50, 40 -> 53.3. Inactive Gone ignored.
        self.assertEqual(data["trend"][0], {"term": "T1", "student": 70.0, "class": 60.0, "year_group": 53.3})
        self.assertEqual(data["trend"][1], {"term": "T2", "student": 90.0, "class": 80.0, "year_group": 63.3})
        self.assertEqual(data["subjects"], [{"subject": "Art", "student": 60.0, "class": 60.0},
                                            {"subject": "Maths", "student": 80.0, "class": 65.0}])

    def test_class(self):
        data = self.get(scope="class", id=self.c7a.id, term=self.t2.id).data
        self.assertEqual(data["trend"][1], {"term": "T2", "class": 80.0, "year_group": 63.3, "school": 72.5})
        self.assertEqual(data["students_count"], 2)
        dist = {d["band"]: d["students"] for d in data["distribution"]}
        self.assertEqual((dist["70–79%"], dist["80% and above"]), (1, 1))
        self.assertEqual([(s["name"], s["average"], s["change"]) for s in data["students"]],
                         [("Ann X", 90.0, 20.0), ("Ben X", 70.0, 20.0)])

    def test_defaults_to_latest_graded_term(self):
        self.assertEqual(self.get(scope="class", id=self.c7a.id).data["term"], self.t2.id)

    def test_year_group(self):
        data = self.get(scope="year_group", id=self.y7.id, term=self.t1.id).data
        self.assertEqual([(g["name"], g["average"]) for g in data["groups"]], [("7A", 60.0), ("7B", 40.0)])
        self.assertEqual(data["trend"][0][f"class_{self.c7a.id}"], 60.0)
        self.assertEqual(data["trend"][0]["year_group"], 53.3)

    def test_school(self):
        data = self.get(scope="school", term=self.t1.id).data
        self.assertEqual(data["students_count"], 4)
        self.assertEqual([(g["name"], g["average"]) for g in data["groups"]], [("Year 7", 53.3), ("Year 8", 100.0)])

    def test_teacher_access(self):
        c = self.client_a
        self.assertEqual(self.get(c, scope="student", id=self.ann.id).status_code, 200)
        self.assertEqual(self.get(c, scope="student", id=self.cy.id).status_code, 404)
        self.assertEqual(self.get(c, scope="class", id=self.c7a.id).status_code, 200)
        self.assertEqual(self.get(c, scope="class", id=self.c7b.id).status_code, 403)
        self.assertEqual(self.get(c, scope="year_group", id=self.c8a.year_group_id).status_code, 403)
        self.assertEqual(self.get(c, scope="school").status_code, 403)
        # In their year group, teachers see averages for every class but only their own students by name.
        data = self.get(c, scope="year_group", id=self.y7.id).data
        self.assertEqual(len(data["groups"]), 2)
        self.assertEqual({s["name"] for s in data["students"]}, {"Ann X", "Ben X"})

    def test_other_school(self):
        self.make_admin(self.user_b)
        c = self.client_b
        self.assertEqual(self.get(c, scope="student", id=self.ann.id).status_code, 404)
        self.assertEqual(self.get(c, scope="class", id=self.c7a.id).status_code, 404)
        self.assertEqual(self.get(c, scope="year_group", id=self.y7.id).status_code, 404)
        self.assertEqual(self.get(c, scope="school").data["students_count"], 1)

    def test_bad_scope(self):
        self.assertEqual(self.get(scope="planet").status_code, 400)
