"""The first-week checklist: its own steps for each system, ticked from what the school has done."""
from datetime import date

from accounts.models import TeachingAssignment
from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from gradebook.models import Grade, StudentSubject, Subject, Term

from .models import SchoolClass, Student, YearGroup


class ChecklistTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)

    def use(self, system):
        self.school_a.education_system = system
        self.school_a.save()

    def steps(self):
        return {s["key"]: s["done"] for s in self.admin.get("/api/checklist/").data["steps"]}

    def test_each_system_has_its_own_steps(self):
        expected = {"cbc": "cbc_competencies", "844": "844_electives", "british": "british_targets",
                    "ib": "ib_atl", "american": "american_credits"}
        for system, key in expected.items():
            self.use(system)
            steps = self.steps()
            self.assertIn(key, steps, system)
            self.assertIn("invite_parents", steps)
            self.assertFalse(any(k.startswith(tuple(f"{o}_" for o in expected if o != system)) for k in steps))

    def test_steps_tick_themselves(self):
        self.use("american")
        self.assertEqual(self.admin.get("/api/checklist/").data["done"], 1)  # teacher_a is already on the staff
        klass = SchoolClass.objects.create(year_group=YearGroup.objects.create(school=self.school_a, name="Grade 9"),
                                           name="9-1")
        art = Subject.objects.create(school=self.school_a, name="Art", credits=0.5, is_elective=True)
        student = Student.objects.create(school=self.school_a, school_class=klass, first_name="Liam", last_name="J")
        self.assign(self.user_a, klass, art)
        StudentSubject.objects.create(student=student, subject=art)
        AttendanceRecord.objects.create(student=student, date=date(2026, 9, 1), status="present")
        Grade.objects.create(student=student, subject=art, term=Term.objects.create(school=self.school_a, name="Fall"),
                             score=90)
        steps = self.steps()
        for key in ("invite_staff", "assign_classes", "add_students", "attendance", "marks", "american_credits",
                    "american_electives"):
            self.assertTrue(steps[key], key)
        self.assertFalse(steps["invite_parents"] or steps["announcement"])
        # Another school's work never ticks this school's steps.
        self.school_b.education_system = "american"
        self.school_b.save()
        self.make_admin(self.user_b)
        other = {s["key"]: s["done"] for s in self.client_b.get("/api/checklist/").data["steps"]}
        self.assertFalse(other["add_students"] or other["marks"] or other["american_credits"])

    def test_diploma_steps_only_for_schools_with_dp(self):
        self.use("ib")
        self.assertNotIn("ib_levels", self.steps())
        YearGroup.objects.create(school=self.school_a, name="DP 1")
        self.assertIn("ib_levels", self.steps())

    def test_admin_can_hide_it_and_teachers_cannot_see_it(self):
        self.assertTrue(self.admin.patch("/api/checklist/", {"hidden": True}, format="json").data["hidden"])
        self.school_a.refresh_from_db()
        self.assertTrue(self.school_a.checklist_hidden)
        self.assertEqual(self.admin.patch("/api/checklist/", {"hidden": "yes"}, format="json").status_code, 400)
        self.assertEqual(self.client_a.get("/api/checklist/").status_code, 403)
