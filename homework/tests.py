"""
Homework and assignments (owner's request, 2026-10-08): teachers set work
for a class and subject and record how each student did; parents see their
child's homework. Students hand in through student accounts.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from accounts.models import StaffRole
from accounts.test_roles import RoleFixture
from activity.models import ActivityLog
from gradebook.models import Subject, StudentSubject
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import Student

from .models import Assignment, HomeworkRecord

URL = "/api/homework/"


class Base(RoleFixture):
    """user_a (client_a) teaches maths in 2 East (Amina); maths_3e teaches maths in 3 East (Cate)."""

    def setUp(self):
        super().setUp()
        self.today = school_localdate(self.school_a)
        self.zed = Student.objects.create(school=self.school_a, first_name="Zed", last_name="A", school_class=self.c2e)
        parent = User.objects.create_user(username="pa@alpha.test", email="pa@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)
        self.parent = self.authed_client(parent)

    def set(self, client=None, **extra):
        body = {"school_class": self.c2e.id, "subject": self.maths.id, "title": "Fractions worksheet",
                "instructions": "Questions 1-10 on page 42.", "due_date": (self.today + timedelta(days=3)).isoformat(),
                "out_of": 10, **extra}
        return (client or self.client_a).post(URL, body, format="json")


class SettingTests(Base):
    def test_a_teacher_sets_homework_for_their_class_and_subject(self):
        response = self.set(link="https://example.com/sheet")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["class_name"], response.data["subject_name"], response.data["set_on"]),
                         ("2 East", "Maths", self.today.isoformat()))
        self.assertEqual(response.data["counts"]["students"], 2)
        self.assertTrue(response.data["can_edit"])
        self.assertTrue(ActivityLog.objects.filter(action="homework.set").exists())

    def test_never_for_classes_or_subjects_they_dont_teach(self):
        self.assertEqual(self.set(school_class=self.c3e.id).status_code, 403)
        self.assertEqual(self.set(subject=self.english.id).status_code, 403)
        other = Subject.objects.create(school=self.school_b, name="Maths")
        self.assertEqual(self.set(subject=other.id).status_code, 400)
        hod = self.staff("hod@alpha.test", "teacher", ("head_of_department", {"subject": self.english}))[1]
        self.assertEqual(self.set(hod, school_class=self.c3e.id, subject=self.english.id).status_code, 201)

    def test_bad_homework(self):
        self.assertEqual(self.set(title=" ").status_code, 400)
        self.assertEqual(self.set(due_date=(self.today - timedelta(days=1)).isoformat()).status_code, 400)
        self.assertEqual(self.set(out_of=0).status_code, 400)
        self.assertEqual(self.set(link="not a link").status_code, 400)

    def test_choices_list_what_a_teacher_can_set(self):
        rows = self.client_a.get(f"{URL}choices/").data
        self.assertEqual([(r["class_name"], r["subject_name"]) for r in rows], [("2 East", "Maths")])

    def test_teachers_see_their_classes_homework_and_only_its_teachers_change_it(self):
        mine = self.set().data["id"]
        theirs = self.set(self.maths_3e[1], school_class=self.c3e.id).data["id"]
        self.assertEqual([r["id"] for r in self.client_a.get(URL).data], [mine])
        self.assertEqual(self.client_a.patch(f"{URL}{theirs}/", {"title": "X"}, format="json").status_code, 404)
        self.assertEqual(self.client_a.patch(f"{URL}{mine}/", {"title": "Fractions, part 2"}, format="json").data["title"],
                         "Fractions, part 2")
        lead = self.staff("lead@alpha.test", "teacher", "leadership")[1]
        self.assertEqual(len(lead.get(URL).data), 2)
        self.assertEqual(lead.delete(f"{URL}{theirs}/").status_code, 204)

    def test_filters(self):
        self.set()
        Assignment.objects.create(school=self.school_a, school_class=self.c2e, subject=self.maths, title="Old",
                                  set_on=self.today - timedelta(days=9), due_date=self.today - timedelta(days=2))
        self.assertEqual([r["title"] for r in self.client_a.get(URL, {"when": "upcoming"}).data], ["Fractions worksheet"])
        self.assertEqual([r["title"] for r in self.client_a.get(URL, {"when": "past"}).data], ["Old"])
        self.assertEqual(len(self.client_a.get(URL, {"mine": 1}).data), 1)


class RecordingTests(Base):
    def test_recording_how_each_student_did(self):
        aid = self.set().data["id"]
        url = f"{URL}{aid}/records/"
        self.assertEqual([(s["name"], s["status"]) for s in self.client_a.get(url).data["students"]],
                         [("Zed A", ""), ("Amina K", "")])
        response = self.client_a.post(url, {"records": [
            {"student": self.amina.id, "status": "handed_in", "mark": 8, "comment": "Good work"},
            {"student": self.zed.id, "status": "missing"}]}, format="json")
        rows = {s["name"]: s for s in response.data["students"]}
        self.assertEqual((rows["Amina K"]["status_label"], float(rows["Amina K"]["mark"])), ("Handed in", 8.0))
        counts = response.data["assignment"]["counts"]
        self.assertEqual((counts["handed_in"], counts["missing"], counts["not_recorded"]), (1, 1, 0))
        # Clearing a status.
        self.client_a.post(url, {"records": [{"student": self.zed.id, "status": ""}]}, format="json")
        self.assertEqual(HomeworkRecord.objects.get(student=self.zed).status, "")

    def test_bad_records(self):
        url = f"{URL}{self.set().data['id']}/records/"
        for rows in ([], [{"student": self.cate.id, "status": "missing"}], [{"student": self.amina.id, "status": "lost"}],
                     [{"student": self.amina.id, "status": "handed_in", "mark": 11}],
                     [{"student": self.amina.id, "status": "handed_in", "mark": "ten"}]):
            self.assertEqual(self.client_a.post(url, {"records": rows}, format="json").status_code, 400, rows)
        self.assertEqual(self.maths_3e[1].post(url, {"records": [{"student": self.amina.id, "status": "missing"}]},
                                               format="json").status_code, 404)

    def test_electives_are_only_for_students_who_chose_them(self):
        art = Subject.objects.create(school=self.school_a, name="Art", is_elective=True)
        StudentSubject.objects.create(student=self.amina, subject=art)
        lead = self.staff("lead@alpha.test", "teacher", "leadership")[1]
        aid = self.set(lead, subject=art.id).data["id"]
        self.assertEqual([s["name"] for s in lead.get(f"{URL}{aid}/records/").data["students"]], ["Amina K"])
        self.assertEqual([h["subject"] for h in self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/").data["homework"]], ["Art"])
        self.assertEqual(lead.post(f"{URL}{aid}/records/", {"records": [{"student": self.zed.id, "status": "missing"}]},
                                   format="json").status_code, 400)


class ParentAndHomeTests(Base):
    def test_parents_see_their_childs_homework_and_how_it_went(self):
        aid = self.set().data["id"]
        Assignment.objects.create(school=self.school_a, school_class=self.c3e, subject=self.maths, title="Not Amina's",
                                  set_on=self.today, due_date=self.today)
        Assignment.objects.create(school=self.school_a, school_class=self.c2e, subject=self.maths, title="Long ago",
                                  set_on=self.today - timedelta(days=60), due_date=self.today - timedelta(days=50))
        overdue = Assignment.objects.create(school=self.school_a, school_class=self.c2e, subject=self.maths, title="Overdue",
                                            set_on=self.today - timedelta(days=5), due_date=self.today - timedelta(days=1))
        self.client_a.post(f"{URL}{aid}/records/", {"records": [{"student": self.amina.id, "status": "late", "comment": "Try harder"},
                                                                {"student": self.zed.id, "status": "missing"}]}, format="json")
        rows = self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/").data["homework"]
        self.assertEqual([r["title"] for r in rows], ["Overdue", "Fractions worksheet"])
        self.assertTrue(rows[0]["overdue"])
        self.assertEqual((rows[1]["status_label"], rows[1]["comment"]), ("Handed in late", "Try harder"))
        self.assertNotIn("Zed", str(rows))
        self.assertEqual(overdue.id, rows[0]["id"])

    def test_the_teachers_home_lists_homework_to_record(self):
        Assignment.objects.create(school=self.school_a, school_class=self.c2e, subject=self.maths, title="Due yesterday",
                                  set_on=self.today - timedelta(days=3), due_date=self.today - timedelta(days=1), set_by=self.user_a)
        (row,) = self.client_a.get("/api/teacher-home/").data["homework"]
        self.assertEqual((row["title"], row["to_record"], row["students"]), ("Due yesterday", 2, 2))


class IsolationTests(Base):
    def setUp(self):
        super().setUp()
        self.aid = self.set().data["id"]
        self.make_admin(self.user_b)

    def test_another_school_reaches_nothing(self):
        self.assertEqual(self.client_b.get(URL).data, [])
        for method in ("get", "patch", "delete"):
            self.assertEqual(getattr(self.client_b, method)(f"{URL}{self.aid}/", {}, format="json").status_code, 404)
        self.assertEqual(self.client_b.get(f"{URL}{self.aid}/records/").status_code, 404)
        self.assertEqual(self.set(self.client_b).status_code, 400)

    def test_parents_governors_and_the_public(self):
        self.assertEqual(self.parent.get(URL).status_code, 403)
        self.assertEqual(APIClient().get(URL).status_code, 401)
        gov = self.staff("gov@alpha.test", "governor")[1]
        self.assertEqual(gov.get(URL).status_code, 403)
        nurse = self.staff("nurse@alpha.test", "teacher", StaffRole.Role.NURSE)[1]
        self.assertEqual(self.set(nurse).status_code, 403)


class PrivacyTests(Base):
    def test_export_and_erasure(self):
        from students.privacy import family_export, family_export_data, remove_personal_data

        aid = self.set().data["id"]
        self.client_a.post(f"{URL}{aid}/records/", {"records": [{"student": self.amina.id, "status": "handed_in", "mark": 7}]},
                           format="json")
        self.assertTrue(family_export(self.amina))
        self.assertEqual(family_export_data(self.amina)["homework"][0]["recorded_as"], "Handed in")
        self.assertEqual(remove_personal_data(self.amina, self.admin_a)["homework_records_deleted"], 1)


class DemoTests(Base):
    def test_demo_homework_once(self):
        from .demo import fill_demo

        added = fill_demo(self.school_a)
        self.assertGreater(added, 0)
        self.assertEqual(fill_demo(self.school_a), 0)
        self.assertTrue(HomeworkRecord.objects.exists())
