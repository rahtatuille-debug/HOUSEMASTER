"""
The timetable: an admin sets the school day and places lessons by hand;
HouseMaster refuses clashes. Teachers see their week and today's lessons,
students' weeks follow their subject choices, and parents see their child's.
"""
from datetime import time

from django.contrib.auth.models import User

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import StudentSubject, Subject
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import SchoolClass, Student, YearGroup

from .models import Lesson, Period, Room
from .services import fill_demo


class TimetableTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        self.teacher = self.authed_client(self.user_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 10")
        self.c10a = SchoolClass.objects.create(year_group=year, name="10A")
        self.c10b = SchoolClass.objects.create(year_group=year, name="10B")
        self.maths = Subject.objects.create(school=self.school_a, name="Mathematics")
        self.french = Subject.objects.create(school=self.school_a, name="French", is_elective=True)
        self.music = Subject.objects.create(school=self.school_a, name="Music", is_elective=True)
        self.assign(self.user_a, self.c10a, self.maths)
        other = User.objects.create_user(username="t2@alpha.test", email="t2@alpha.test", password="x")
        self.other = Profile.objects.create(user=other, school=self.school_a, role="teacher", display_name="Mr Other")
        self.p1 = Period.objects.create(school=self.school_a, name="Lesson 1", start_time=time(8), end_time=time(8, 40))
        self.brk = Period.objects.create(school=self.school_a, name="Break", start_time=time(8, 40),
                                         end_time=time(9), is_break=True)
        self.p2 = Period.objects.create(school=self.school_a, name="Lesson 2", start_time=time(9), end_time=time(9, 40))
        self.lab = Room.objects.create(school=self.school_a, name="Lab 1")
        self.ann = Student.objects.create(school=self.school_a, first_name="Ann", last_name="K", school_class=self.c10a)
        self.ben = Student.objects.create(school=self.school_a, first_name="Ben", last_name="K", school_class=self.c10a)
        StudentSubject.objects.create(student=self.ann, subject=self.french)
        StudentSubject.objects.create(student=self.ben, subject=self.music)

    def place(self, client=None, **body):
        body = {"school_class": self.c10a.id, "subject": self.maths.id, "day": 1, "period": self.p1.id, **body}
        return (client or self.admin).post("/api/timetable/lessons/", body, format="json")

    def errors(self, response):
        self.assertEqual(response.status_code, 400, response.data)
        return " ".join(str(e) for e in response.data.get("non_field_errors", response.data.values()))

    # --- the school day

    def test_a_standard_day_with_breaks(self):
        Period.objects.filter(school=self.school_a).delete()
        response = self.admin.post("/api/timetable/periods/standard/", {
            "start": "08:00", "lesson_minutes": 40, "lessons": 4,
            "breaks": [{"after": 2, "minutes": 20, "name": "Break"}]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([(p["name"], p["start_time"][:5], p["is_break"]) for p in response.data], [
            ("Lesson 1", "08:00", False), ("Lesson 2", "08:40", False), ("Break", "09:20", True),
            ("Lesson 3", "09:40", False), ("Lesson 4", "10:20", False)])

    def test_a_standard_day_is_refused_once_there_are_lessons(self):
        self.place()
        response = self.admin.post("/api/timetable/periods/standard/", {"lessons": 6}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Period.objects.filter(school=self.school_a).count(), 3)

    def test_periods_cannot_overlap(self):
        response = self.admin.post("/api/timetable/periods/", {"name": "X", "start_time": "08:20",
                                                               "end_time": "09:10"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_teaching_days(self):
        self.assertEqual(self.admin.get("/api/timetable/school-week/").data["days"], [1, 2, 3, 4, 5])
        self.assertEqual(self.admin.patch("/api/timetable/school-week/", {"days": [1, 2, 3, 4, 5, 6]},
                                          format="json").data["days"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(self.place(day=6).status_code, 201)
        self.assertEqual(self.admin.patch("/api/timetable/school-week/", {"days": [1, 2, 3, 4, 5]},
                                          format="json").status_code, 400)  # a Saturday lesson is in the way

    # --- placing lessons

    def test_the_teacher_comes_from_the_staff_page(self):
        response = self.place(room=self.lab.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["teacher_name"], response.data["room_name"]),
                         (self.user_a.profile.name, "Lab 1"))

    def test_teacher_and_room_clashes(self):
        self.place(room=self.lab.id)
        self.assertIn("already teaches 10A Mathematics", self.errors(
            self.place(school_class=self.c10b.id, teacher=self.user_a.profile.id)))
        self.assertIn("Lab 1 is already used", self.errors(
            self.place(school_class=self.c10b.id, teacher=self.other.id, room=self.lab.id)))
        self.assertEqual(self.place(school_class=self.c10b.id, teacher=self.other.id).status_code, 201)

    def test_a_class_cannot_have_two_lessons_at_once(self):
        self.place()
        self.assertIn("10A already has Mathematics", self.errors(self.place(subject=self.french.id,
                                                                            teacher=self.other.id)))

    def test_electives_with_no_shared_students_can_run_side_by_side(self):
        self.assertEqual(self.place(subject=self.french.id, teacher=None).status_code, 201)
        self.assertEqual(self.place(subject=self.music.id, teacher=self.other.id).status_code, 201)
        StudentSubject.objects.create(student=self.ann, subject=self.music)
        lesson = Lesson.objects.get(subject=self.music)
        response = self.admin.patch(f"/api/timetable/lessons/{lesson.id}/", {"day": 1}, format="json")
        self.assertIn("1 student in 10A take both", self.errors(response))

    def test_the_same_subject_more_than_once_a_day(self):
        self.assertEqual(self.place().status_code, 201)
        self.assertEqual(self.place(period=self.p2.id).status_code, 201)  # a double lesson
        self.assertEqual(Lesson.objects.filter(school_class=self.c10a, subject=self.maths, day=1).count(), 2)

    def test_no_lessons_in_breaks_or_on_days_off(self):
        self.assertIn("is a break", self.errors(self.place(period=self.brk.id)))
        self.assertEqual(self.place(day=7).status_code, 400)

    def test_a_lesson_without_a_subject_needs_a_title(self):
        self.assertEqual(self.place(subject=None).status_code, 400)
        self.assertEqual(self.place(subject=None, title="Assembly").data["label"], "Assembly")

    def test_only_admins_change_it(self):
        self.assertEqual(self.place(client=self.teacher).status_code, 403)
        self.assertEqual(self.teacher.get("/api/timetable/periods/").status_code, 200)

    def test_other_schools_cannot_see_or_use_it(self):
        b_admin = User.objects.create_user(username="ab@beta.test", email="ab@beta.test", password="x")
        Profile.objects.create(user=b_admin, school=self.school_b, role="admin")
        other = self.authed_client(b_admin)
        self.place()
        self.assertEqual(other.get("/api/timetable/lessons/").data, [])
        self.assertEqual(self.place(client=other).status_code, 400)  # 10A and the period aren't theirs
        self.assertEqual(other.get("/api/timetable/week/", {"school_class": self.c10a.id}).status_code, 404)

    # --- seeing it

    def test_weeks_by_class_teacher_room_and_student(self):
        self.place(room=self.lab.id)
        self.place(subject=self.french.id, teacher=self.other.id, period=self.p2.id)
        self.place(subject=self.music.id, teacher=None, period=self.p2.id, day=2)
        mine = self.teacher.get("/api/timetable/week/").data
        self.assertEqual([lesson["label"] for lesson in mine["lessons"]], ["Mathematics"])
        self.assertEqual(len(self.teacher.get("/api/timetable/week/", {"school_class": self.c10a.id})
                             .data["lessons"]), 3)
        self.assertEqual(len(self.admin.get("/api/timetable/week/", {"room": self.lab.id}).data["lessons"]), 1)
        ann = self.admin.get("/api/timetable/week/", {"student": self.ann.id}).data
        self.assertEqual(sorted(lesson["label"] for lesson in ann["lessons"]), ["French", "Mathematics"])
        self.assertEqual([d["name"] for d in ann["days"]][:2], ["Monday", "Tuesday"])
        self.assertTrue(ann["periods"][1]["is_break"])

    def test_teachers_see_only_their_students_weeks(self):
        other_class = Student.objects.create(school=self.school_a, first_name="Cy", last_name="K",
                                             school_class=self.c10b)
        self.assertEqual(self.teacher.get("/api/timetable/week/", {"student": other_class.id}).status_code, 404)

    def test_today_on_the_teacher_home(self):
        self.place(day=school_localdate(self.school_a).isoweekday() if school_localdate(self.school_a)
                   .isoweekday() <= 5 else 1)
        today = self.teacher.get("/api/teacher-home/").data["today"]
        if school_localdate(self.school_a).isoweekday() <= 5:
            self.assertEqual([(t["class_name"], t["label"], t["start_time"]) for t in today],
                             [("10A", "Mathematics", "08:00")])
        else:
            self.assertEqual(today, [])

    def test_parents_see_their_childs_week(self):
        self.place()
        self.place(subject=self.music.id, teacher=None, period=self.p2.id)
        parent = User.objects.create_user(username="p@alpha.test", email="p@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="P").students.add(self.ann)
        week = self.authed_client(parent).get(f"/api/guardian-students/{self.ann.id}/timetable/").data
        self.assertEqual([lesson["label"] for lesson in week["lessons"]], ["Mathematics"])  # Ann doesn't take music
        self.assertEqual(self.authed_client(parent).get(f"/api/guardian-students/{self.ben.id}/timetable/")
                         .status_code, 404)


class DemoTimetableTests(SchoolScopedAPITestCase):
    def test_fills_without_clashes(self):
        from .services import clashes

        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        classes = [SchoolClass.objects.create(year_group=year, name=f"7{c}") for c in "AB"]
        subjects = [Subject.objects.create(school=self.school_a, name=n) for n in ("English", "Mathematics", "Art")]
        for klass in classes:
            for subject in subjects:
                self.assign(self.user_a if subject.name == "Mathematics" else self.admin_a, klass, subject)
        placed = fill_demo(self.school_a, rooms=2)
        self.assertEqual(placed, 2 * (4 + 4 + 2))
        for lesson in Lesson.objects.filter(school=self.school_a):
            self.assertEqual(clashes(lesson), [], lesson.label)
        self.assertEqual(Period.objects.filter(school=self.school_a, is_break=True).count(), 2)
