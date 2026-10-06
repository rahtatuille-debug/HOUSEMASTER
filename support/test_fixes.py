"""
C-1: warning signs need enough data, the pass mark can differ per year group, a dismissed suggestion comes back
when things get clearly worse, and a student who is new since last term isn't flagged for a "big drop".
"""
from datetime import date

from django.test import override_settings

from gradebook.models import Grade
from students.models import School, Student, YearGroup

from .tests import SupportTests


def load_tests(loader, tests, pattern):
    # Only the tests written here: the fixture comes from SupportTests, whose own tests run there.
    names = [n for n in vars(SupportThresholdTests) if n.startswith("test_")]
    return loader.suiteClass(SupportThresholdTests(n) for n in sorted(names))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class SupportThresholdTests(SupportTests):
    def few_marks(self, name, score, t1_marks=3, t2_marks=1, days=10):
        s = Student.objects.create(school=self.school_a, first_name=name, last_name="K", school_class=self.c7a)
        for _ in range(t1_marks):
            Grade.objects.create(student=s, subject=self.maths, term=self.t1, score=score)
        for _ in range(t2_marks):
            Grade.objects.create(student=s, subject=self.maths, term=self.t2, score=score)
        return s

    def test_one_low_mark_is_not_enough_to_suggest_support(self):
        one = self.few_marks("Quiz", 10, t2_marks=1)
        response = self.admin.get("/api/support/suggestions/", {"term": self.t2.id}).data
        self.assertNotIn(one.id, {r["student"] for r in response["results"]})
        waiting = {r["student"]: r for r in response["not_enough_data"]}
        self.assertIn("1 of 3 marks", waiting[one.id]["detail"])
        School.objects.filter(pk=self.school_a.pk).update(support_min_marks=1)
        self.assertIn(one.id, self.suggestions())

    def test_a_few_days_of_attendance_are_not_enough(self):
        from attendance.models import AttendanceRecord

        AttendanceRecord.objects.filter(student=self.absent).exclude(status="absent").delete()  # 4 days, all absent
        self.assertNotIn("poor_attendance", {r["code"] for r in self.suggestions().get(self.absent.id, {"reasons": []})["reasons"]})
        School.objects.filter(pk=self.school_a.pk).update(support_min_days=3)
        self.assertIn("poor_attendance", {r["code"] for r in self.suggestions()[self.absent.id]["reasons"]})

    def test_the_pass_mark_can_differ_for_a_year_group(self):
        self.assertNotIn(self.fine.id, self.suggestions())  # 75 is above the school's 40
        YearGroup.objects.filter(pk=self.c7a.year_group_id).update(support_pass_mark=80)
        found = self.suggestions()
        self.assertIn("below the pass mark of 80%", found[self.fine.id]["reasons"][0]["label"])
        response = self.admin.patch(f"/api/year-groups/{self.c7a.year_group_id}/", {"support_pass_mark": 60},
                                    format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["support_pass_mark"], 60)

    def test_a_dismissed_suggestion_comes_back_when_it_gets_clearly_worse(self):
        self.admin.post("/api/support/concerns/dismiss/", {"student": self.low.id, "term": self.t2.id}, format="json")
        self.assertNotIn(self.low.id, self.suggestions())
        Grade.objects.create(student=self.low, subject=self.maths, term=self.t2, score=25)  # a little worse
        self.assertNotIn(self.low.id, self.suggestions())
        for _ in range(3):
            Grade.objects.create(student=self.low, subject=self.maths, term=self.t2, score=0)  # clearly worse
        found = self.suggestions()
        self.assertIn(self.low.id, found)
        self.assertIn("since the suggestion was dismissed", found[self.low.id]["reasons"][-1]["label"])

    def test_a_student_new_since_last_term_is_not_flagged_for_a_big_drop(self):
        Student.objects.filter(pk=self.drop.pk).update(enrolled_on=date(2026, 3, 1))  # joined late in T1
        self.assertNotIn("big_drop", {r["code"] for r in self.suggestions().get(self.drop.id, {"reasons": []})["reasons"]})
        Student.objects.filter(pk=self.drop.pk).update(enrolled_on=date(2025, 9, 1))
        self.assertIn("big_drop", {r["code"] for r in self.suggestions()[self.drop.id]["reasons"]})

    def test_admins_set_the_new_limits(self):
        response = self.admin.patch(f"/api/schools/{self.school_a.id}/", {
            "support_min_marks": 4, "support_min_days": 15, "support_reopen_points": 5}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.school_a.refresh_from_db()
        self.assertEqual((self.school_a.support_min_marks, self.school_a.support_min_days,
                          self.school_a.support_reopen_points), (4, 15, 5))

    def test_a_suggestion_that_came_back_can_be_confirmed(self):
        self.admin.post("/api/support/concerns/dismiss/", {"student": self.low.id, "term": self.t2.id}, format="json")
        for _ in range(3):
            Grade.objects.create(student=self.low, subject=self.maths, term=self.t2, score=0)
        codes = [r["code"] for r in self.suggestions()[self.low.id]["reasons"]]
        response = self.confirm(self.low, reasons=codes)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("since the suggestion was dismissed", str(response.data["reasons"]))
