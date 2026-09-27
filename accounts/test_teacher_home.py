"""A teacher's home page, getting-started checklist and guided tour."""
from datetime import date

from gradebook.models import Subject

from students.models import SchoolClass, Student, YearGroup

from .tests import SchoolScopedAPITestCase


class TeacherHomeTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.school_a.education_system = "cbc"
        self.school_a.save()
        year = YearGroup.objects.create(school=self.school_a, name="Grade 7")
        self.east = SchoolClass.objects.create(year_group=year, name="7 East")
        self.west = SchoolClass.objects.create(year_group=year, name="7 West")
        self.maths = Subject.objects.create(school=self.school_a, name="Mathematics")
        self.amina = Student.objects.create(school=self.school_a, school_class=self.east, first_name="Amina",
                                            last_name="O")
        self.assign(self.user_a, self.east, None)
        self.assign(self.user_a, self.west, self.maths)

    def home(self, client=None):
        return (client or self.client_a).get("/api/teacher-home/").data

    def test_home_lists_the_teachers_classes(self):
        classes = {c["name"]: c for c in self.home()["classes"]}
        self.assertEqual(set(classes), {"7 East", "7 West"})
        self.assertTrue(classes["7 East"]["class_teacher"])
        self.assertEqual((classes["7 West"]["subjects"], classes["7 East"]["students"]), (["Mathematics"], 1))
        self.assertFalse(classes["7 East"]["register_taken_today"])
        # Another school's teacher sees none of it.
        self.assertEqual(self.home(self.client_b)["classes"], [])

    def test_checklist_ticks_itself(self):
        steps = {s["key"]: s["done"] for s in self.home()["checklist"]["steps"]}
        self.assertEqual(set(steps), {"tour", "register", "marks", "comments", "reports", "message"})
        self.assertFalse(any(steps.values()))
        self.client_a.post("/api/attendance/", {"student": self.amina.id, "date": date.today().isoformat(),
                                                "status": "present"}, format="json")
        self.assertEqual(self.client_a.post("/api/tour-seen/").status_code, 200)
        data = self.home()
        steps = {s["key"]: s["done"] for s in data["checklist"]["steps"]}
        self.assertTrue(steps["register"] and steps["tour"])
        self.assertTrue({c["name"]: c for c in data["classes"]}["7 East"]["register_taken_today"])
        self.assertTrue(self.client_a.get("/api/me/").data["tour_seen"])

    def test_subject_teachers_have_no_report_step(self):
        self.user_b.profile.assignments.all().delete()
        self.assertNotIn("reports", {s["key"] for s in self.home(self.client_b)["checklist"]["steps"]})

    def test_checklist_can_be_hidden(self):
        data = self.client_a.patch("/api/teacher-home/", {"hidden": True}, format="json").data
        self.assertTrue(data["checklist"]["hidden"])
        self.assertEqual(self.client_a.patch("/api/teacher-home/", {"hidden": "no"}, format="json").status_code, 400)
