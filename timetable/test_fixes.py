"""
F: deactivating a teacher lists their lessons and they show as unstaffed; changing students' options re-checks
the class's timetable and reports new clashes.
"""
from .models import Lesson
from .tests import TimetableTests


def load_tests(loader, tests, pattern):
    # Only the tests written here: the fixture comes from TimetableTests, whose own tests run there.
    names = [n for c in (UnstaffedTests, OptionClashTests) for n in vars(c) if n.startswith("test_")]
    return loader.suiteClass([c(n) for c in (UnstaffedTests, OptionClashTests) for n in sorted(vars(c))
                              if n.startswith("test_")]) if names else tests


class UnstaffedTests(TimetableTests):
    def test_deactivating_a_teacher_lists_their_lessons_and_they_show_as_unstaffed(self):
        self.place(teacher=self.other.id)
        self.place(teacher=self.other.id, period=self.p2.id)
        self.place(day=2, teacher=self.user_a.profile.id)
        response = self.admin.post(f"/api/staff/{self.other.id}/deactivate/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["lessons"]), 2)
        self.assertIn("Mathematics", response.data["lessons"][0]["label"])
        unstaffed = self.admin.get("/api/timetable/unstaffed/").data
        self.assertEqual(len(unstaffed), 2)
        self.assertEqual({row["teacher_name"] for row in unstaffed}, {"Mr Other (inactive)"})
        self.assertEqual(Lesson.objects.filter(teacher=self.other).count(), 2)  # history kept, not erased

    def test_a_lesson_with_no_teacher_is_unstaffed_too_and_giving_one_fixes_it(self):
        lesson_id = self.place(teacher=None).data["id"]
        self.assertEqual([r["id"] for r in self.admin.get("/api/timetable/unstaffed/").data], [lesson_id])
        self.admin.patch(f"/api/timetable/lessons/{lesson_id}/", {"teacher": self.other.id}, format="json")
        self.assertEqual(self.admin.get("/api/timetable/unstaffed/").data, [])

    def test_only_this_schools_lessons_and_only_staff(self):
        self.place(teacher=None)
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get("/api/timetable/unstaffed/").data, [])
        self.assertEqual(self.teacher.get("/api/timetable/unstaffed/").status_code, 200)  # staff can read


class OptionClashTests(TimetableTests):
    def test_changing_options_reports_the_clashes_it_creates(self):
        # French and Music share a slot: fine while nobody takes both.
        self.assertEqual(self.place(subject=self.french.id, teacher=self.other.id).status_code, 201)
        self.assertEqual(self.place(subject=self.music.id, teacher=None).status_code, 201)
        response = self.admin.post("/api/subject-choices/", {"school_class": self.c10a.id, "students": [
            {"student": self.ann.id, "subjects": [{"subject": self.french.id, "level": ""},
                                                  {"subject": self.music.id, "level": ""}]}]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["timetable_clashes"]), 1)
        self.assertIn("take both", response.data["timetable_clashes"][0])

    def test_no_clash_no_warning(self):
        self.place(subject=self.french.id, teacher=self.other.id)
        response = self.admin.post("/api/subject-choices/", {"school_class": self.c10a.id, "students": [
            {"student": self.ben.id, "subjects": [{"subject": self.music.id, "level": ""}]}]}, format="json")
        self.assertEqual(response.data["timetable_clashes"], [])
