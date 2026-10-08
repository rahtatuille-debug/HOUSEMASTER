"""
Student accounts (owner's request, 2026-10-08): school-made logins; a
student sees what their parents see about them and nothing else, chooses
their own password first, and hands in homework.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from accounts.test_roles import RoleFixture
from activity.models import ActivityLog
from guardians.models import Guardian
from homework.models import Assignment, HomeworkRecord
from schoolcalendar.models import Event
from students.localtime import school_localdate

from .models import StudentAccount

ACCOUNTS = "/api/student-accounts/"


class Base(RoleFixture):
    def setUp(self):
        super().setUp()
        self.today = school_localdate(self.school_a)
        parent = User.objects.create_user(username="pa@alpha.test", email="pa@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)
        self.parent = self.authed_client(parent)

    def make(self, student=None, client=None):
        response = (client or self.admin).post(ACCOUNTS, {"students": [(student or self.amina).id]}, format="json")
        return response

    def login(self, username, password):
        return APIClient().post("/api/token/", {"email": username, "password": password}, format="json")

    def signed_in(self, student=None, choose=True):
        """A client signed in as the student, having chosen their own password."""
        made = self.make(student).data["created"][0]
        tokens = self.login(made["username"], made["password"]).data
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        if choose:
            new = client.post("/api/student/password/", {"current_password": made["password"],
                                                          "new_password": "Correct-Horse-Battery-9"}, format="json").data
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {new['access']}")
        return client, made


class ManagingTests(Base):
    def test_an_admin_makes_accounts_and_sees_the_starting_password_once(self):
        response = self.admin.post(ACCOUNTS, {"students": [self.amina.id, self.ben.id]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        rows = {r["name"]: r for r in response.data["created"]}
        self.assertNotIn("@", rows["Amina K"]["username"])
        self.assertTrue(rows["Amina K"]["username"].startswith("amina.k"))
        self.assertRegex(rows["Amina K"]["password"], r"^[a-z]+-[a-z]+-\d\d$")
        listed = {r["name"]: r for r in self.admin.get(ACCOUNTS).data}
        self.assertTrue(listed["Amina K"]["has_account"] and listed["Amina K"]["must_change_password"])
        self.assertFalse(any("password" in row for row in self.admin.get(ACCOUNTS).data))
        self.assertFalse(listed["Cate K"]["has_account"])
        again = self.admin.post(ACCOUNTS, {"students": [self.amina.id]}, format="json").data
        self.assertEqual((again["created"], again["already"]), ([], 1))
        entry = ActivityLog.objects.get(action="student_accounts.created")
        self.assertNotIn(rows["Amina K"]["password"], entry.summary + str(entry.details))

    def test_who_can_manage(self):
        self.assertEqual(self.make(client=self.client_a).status_code, 403)  # a teacher
        self.assertEqual(self.client_a.get(ACCOUNTS).status_code, 403)
        secretary = self.staff("sec@alpha.test", "teacher", "secretary")[1]
        self.assertEqual(self.make(client=secretary).status_code, 201)
        lead = self.staff("lead@alpha.test", "teacher", "leadership")[1]
        self.assertEqual(self.make(self.ben, client=lead).status_code, 201)
        self.assertEqual(self.parent.get(ACCOUNTS).status_code, 403)

    def test_reset_disable_enable_and_remove(self):
        made = self.make().data["created"][0]
        reset = self.admin.post(f"{ACCOUNTS}{self.amina.id}/reset/").data
        self.assertNotEqual(reset["password"], made["password"])
        self.assertEqual(self.login(made["username"], made["password"]).status_code, 401)
        self.assertEqual(self.login(made["username"], reset["password"]).status_code, 200)
        self.admin.post(f"{ACCOUNTS}{self.amina.id}/disable/")
        self.assertEqual(self.login(made["username"], reset["password"]).status_code, 401)
        self.admin.post(f"{ACCOUNTS}{self.amina.id}/enable/")
        self.assertEqual(self.login(made["username"], reset["password"]).status_code, 200)
        self.assertEqual(self.admin.delete(f"{ACCOUNTS}{self.amina.id}/").status_code, 204)
        self.assertFalse(User.objects.filter(username=made["username"]).exists())
        self.assertEqual(self.admin.post(f"{ACCOUNTS}{self.amina.id}/reset/").status_code, 400)

    def test_bad_requests(self):
        self.assertEqual(self.admin.post(ACCOUNTS, {"students": []}, format="json").status_code, 400)
        self.assertEqual(self.admin.post(ACCOUNTS, {"students": ["x"]}, format="json").status_code, 400)
        self.assertEqual(self.admin.post(ACCOUNTS, {"students": list(range(1, 300))}, format="json").status_code, 400)


class SigningInTests(Base):
    def test_a_student_signs_in_with_their_username_and_must_choose_a_password(self):
        made = self.make().data["created"][0]
        response = self.login(made["username"].upper(), made["password"])
        self.assertEqual(response.status_code, 200)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        me = client.get("/api/student/me/").data
        self.assertEqual((me["role"], me["name"], me["must_change_password"]), ("student", "Amina K", True))
        blocked = client.get("/api/guardian-students/")
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.data["code"], "password_change_required")
        # Wrong current password, the same password, a weak one.
        for body in ({"current_password": "nope", "new_password": "Correct-Horse-Battery-9"},
                     {"current_password": made["password"], "new_password": made["password"]},
                     {"current_password": made["password"], "new_password": "short"}):
            self.assertEqual(client.post("/api/student/password/", body, format="json").status_code, 400)
        tokens = client.post("/api/student/password/", {"current_password": made["password"],
                                                        "new_password": "Correct-Horse-Battery-9"}, format="json").data
        self.assertEqual(client.get("/api/student/me/").status_code, 401)  # the old session ended
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertFalse(client.get("/api/student/me/").data["must_change_password"])
        self.assertEqual([s["id"] for s in client.get("/api/guardian-students/").data], [self.amina.id])

    def test_usernames_only_work_for_student_accounts(self):
        weird = User.objects.create_user(username="plainname", email="", password="Correct-Horse-Battery-9")
        self.assertEqual(self.login("plainname", "Correct-Horse-Battery-9").status_code, 401)
        self.assertEqual(self.login(self.user_a.username.split("@")[0], "pass1234").status_code, 401)
        self.assertTrue(weird.pk)

    def test_a_student_who_has_left_cannot_sign_in(self):
        client, made = self.signed_in()
        self.amina.is_active = False
        self.amina.save()
        self.assertEqual(self.login(made["username"], "Correct-Horse-Battery-9").status_code, 401)
        self.assertEqual(client.get("/api/student/me/").status_code, 403)


class WhatAStudentSeesTests(Base):
    def test_only_their_own_record(self):
        client, _ = self.signed_in()
        self.assertEqual(client.get(f"/api/guardian-students/{self.amina.id}/profile/").status_code, 200)
        self.assertEqual(client.get(f"/api/guardian-students/{self.amina.id}/grades/").status_code, 200)
        self.assertEqual(client.get(f"/api/guardian-students/{self.amina.id}/timetable/").status_code, 200)
        for other in (self.ben, self.cate):
            self.assertEqual(client.get(f"/api/guardian-students/{other.id}/profile/").status_code, 404)

    def test_nothing_staff_or_parents_only(self):
        client, _ = self.signed_in()
        for url in ("/api/students/", "/api/me/", "/api/guardian-me/", "/api/homework/", "/api/conversations/",
                    "/api/calendar/events/", "/api/discipline/incidents/", ACCOUNTS, "/api/clubs/",
                    "/api/announcements/", f"/api/students/{self.amina.id}/profile/"):
            self.assertEqual(client.get(url).status_code, 403, url)
        self.assertEqual(client.post(f"/api/guardian-students/{self.amina.id}/health-notes-request/",
                                     {"medical_notes": "x"}, format="json").status_code, 403)
        self.assertEqual(client.post(f"/api/guardian-students/{self.amina.id}/leave-requests/", {}, format="json").status_code, 403)

    def test_the_calendar_for_their_year(self):
        Event.objects.create(school=self.school_a, title="Form 2 trip", start_date=self.today).year_groups.add(self.form2)
        Event.objects.create(school=self.school_a, title="Form 3 trip", start_date=self.today).year_groups.add(self.form3)
        Event.objects.create(school=self.school_a, title="Staff training", start_date=self.today, staff_only=True)
        client, _ = self.signed_in()
        titles = [i["title"] for i in client.get("/api/calendar/").data["items"]]
        self.assertEqual(titles, ["Form 2 trip"])
        self.assertTrue(client.get("/api/calendar/feed/").data["url"].endswith(".ics"))

    def test_another_schools_student_reaches_nothing_here(self):
        from students.models import Student

        other = Student.objects.create(school=self.school_b, first_name="Zed", last_name="B")
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.post(ACCOUNTS, {"students": [self.amina.id]}, format="json").status_code, 400)
        self.assertEqual(self.client_b.post(f"{ACCOUNTS}{self.amina.id}/reset/").status_code, 404)
        made = self.client_b.post(ACCOUNTS, {"students": [other.id]}, format="json").data["created"][0]
        tokens = self.login(made["username"], made["password"]).data
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        new = client.post("/api/student/password/", {"current_password": made["password"],
                                                     "new_password": "Correct-Horse-Battery-9"}, format="json").data
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {new['access']}")
        self.assertEqual(client.get(f"/api/guardian-students/{self.amina.id}/profile/").status_code, 404)
        self.assertNotIn("Amina", str(client.get("/api/calendar/").data))


class HandInTests(Base):
    def setUp(self):
        super().setUp()
        self.hw = Assignment.objects.create(school=self.school_a, school_class=self.c2e, subject=self.maths, title="Fractions",
                                            set_on=self.today, due_date=self.today + timedelta(days=2))
        self.other = Assignment.objects.create(school=self.school_a, school_class=self.c2w, subject=self.maths,
                                               title="Not hers", set_on=self.today, due_date=self.today)

    def test_hand_in_with_an_answer_and_take_it_back(self):
        client, _ = self.signed_in()
        response = client.post(f"/api/student/homework/{self.hw.id}/", {"done": True, "answer": "https://docs.example/mine"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["done_at"])
        mine = [h for h in client.get(f"/api/guardian-students/{self.amina.id}/profile/").data["homework"] if h["id"] == self.hw.id][0]
        self.assertEqual(mine["answer"], "https://docs.example/mine")
        teacher_view = {s["name"]: s for s in self.client_a.get(f"/api/homework/{self.hw.id}/records/").data["students"]}
        self.assertEqual(teacher_view["Amina K"]["answer"], "https://docs.example/mine")
        parent_view = [h for h in self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/").data["homework"]
                       if h["id"] == self.hw.id][0]
        self.assertIsNotNone(parent_view["done_at"])
        client.post(f"/api/student/homework/{self.hw.id}/", {"done": False}, format="json")
        self.assertEqual(HomeworkRecord.objects.get(student=self.amina).answer, "")

    def test_not_other_homework_and_not_after_the_teacher_records_it(self):
        client, _ = self.signed_in()
        self.assertEqual(client.post(f"/api/student/homework/{self.other.id}/", {"done": True}, format="json").status_code, 404)
        HomeworkRecord.objects.create(assignment=self.hw, student=self.amina, status="handed_in")
        self.assertEqual(client.post(f"/api/student/homework/{self.hw.id}/", {"done": False}, format="json").status_code, 400)
        self.assertEqual(self.client_a.post(f"/api/student/homework/{self.hw.id}/", {"done": True}, format="json").status_code, 403)
        self.assertEqual(self.parent.post(f"/api/student/homework/{self.hw.id}/", {"done": True}, format="json").status_code, 403)


class PrivacyTests(Base):
    def test_export_and_erasure_and_deleting_the_student(self):
        from students.privacy import family_export, family_export_data, remove_personal_data

        made = self.make().data["created"][0]
        self.assertTrue(family_export(self.amina))
        self.assertEqual(family_export_data(self.amina)["student_account"]["username"], made["username"])
        self.assertEqual(remove_personal_data(self.amina, self.admin_a)["student_account_deleted"], 1)
        self.assertFalse(User.objects.filter(username=made["username"]).exists())
        made = self.make(self.ben).data["created"][0]
        self.ben.delete()
        self.assertFalse(User.objects.filter(username=made["username"]).exists())
        self.assertFalse(StudentAccount.objects.exists())
