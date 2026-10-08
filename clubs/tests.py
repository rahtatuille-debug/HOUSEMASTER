"""
Clubs and activities (owner's request, 2026-10-08): clubs and teams, their
members, registers, fixtures and results. Leadership sets up clubs and
chooses their staff; the club's staff run them; every staff member sees
them; parents see their own child's.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from accounts.test_roles import RoleFixture
from activity.models import ActivityLog
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import Student

from .models import Club, ClubAttendance, ClubMember, ClubSession, Fixture

CLUBS = "/api/clubs/"
FIXTURES = "/api/fixtures/"


class Base(RoleFixture):
    def setUp(self):
        super().setUp()
        self.today = school_localdate(self.school_a)
        self.lead = self.staff("lead@alpha.test", "teacher", "leadership")[1]
        self.coach_user, self.coach = self.staff("coach@alpha.test")
        self.club = Club.objects.create(school=self.school_a, name="Football", kind="sport", meets="Tuesdays 3:30pm")
        self.club.leaders.add(self.coach_user)
        for s in (self.amina, self.ben):
            ClubMember.objects.create(club=self.club, student=s, joined_on=self.today)
        parent = User.objects.create_user(username="pa@alpha.test", email="pa@alpha.test", password="x")
        guardian = Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat")
        guardian.students.add(self.amina)
        self.parent = self.authed_client(parent)

    def fixture(self, **extra):
        body = {"club": self.club.id, "date": (self.today + timedelta(days=3)).isoformat(), "opponent": "St Mary's",
                "venue": "away", "team": "Under 15", **extra}
        return self.coach.post(FIXTURES, body, format="json")


class SettingUpClubsTests(Base):
    def test_leadership_adds_a_club_and_chooses_its_staff(self):
        response = self.lead.post(CLUBS, {"name": "Chess", "kind": "club", "meets": "Fridays at lunch",
                                          "leaders": [self.coach_user.id]}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["leaders"], response.data["kind_label"]), (["coach"], "Club or society"))
        self.assertTrue(ActivityLog.objects.filter(action="clubs.created").exists())
        self.assertEqual(self.lead.post(CLUBS, {"name": "chess"}, format="json").status_code, 400)  # same name

    def test_teachers_cannot_add_or_remove_clubs_or_choose_staff(self):
        self.assertEqual(self.client_a.post(CLUBS, {"name": "Chess"}, format="json").status_code, 403)
        self.assertEqual(self.coach.delete(f"{CLUBS}{self.club.id}/").status_code, 403)
        self.assertEqual(self.coach.patch(f"{CLUBS}{self.club.id}/", {"leaders": []}, format="json").status_code, 403)
        self.assertEqual(self.coach.get(f"{CLUBS}staff/").status_code, 403)
        # The club's staff can change its details, nobody else (apart from leadership).
        self.assertEqual(self.coach.patch(f"{CLUBS}{self.club.id}/", {"meets": "Wednesdays"}, format="json").status_code, 200)
        self.assertEqual(self.client_a.patch(f"{CLUBS}{self.club.id}/", {"meets": "Never"}, format="json").status_code, 403)

    def test_leaders_must_be_staff_of_this_school(self):
        for bad in ([self.user_b.id], ["x"]):
            self.assertEqual(self.lead.patch(f"{CLUBS}{self.club.id}/", {"leaders": bad}, format="json").status_code, 400)
        gov = self.staff("gov@alpha.test", "governor")[0]
        self.assertEqual(self.lead.patch(f"{CLUBS}{self.club.id}/", {"leaders": [gov.id]}, format="json").status_code, 400)
        names = [s["name"] for s in self.lead.get(f"{CLUBS}staff/").data]
        self.assertIn("coach", names)
        self.assertNotIn("gov", names)

    def test_every_teacher_sees_the_clubs_and_mine_filters(self):
        rows = self.client_a.get(CLUBS).data
        self.assertEqual([(r["name"], r["member_count"], r["can_manage"]) for r in rows], [("Football", 2, False)])
        self.assertEqual(len(self.coach.get(CLUBS, {"mine": 1}).data), 1)
        self.assertEqual(self.client_a.get(CLUBS, {"mine": 1}).data, [])
        self.assertTrue(self.coach.get(f"{CLUBS}{self.club.id}/").data["can_manage"])

    def test_removing_a_club_takes_everything_with_it(self):
        self.fixture()
        self.assertEqual(self.lead.delete(f"{CLUBS}{self.club.id}/").status_code, 204)
        self.assertFalse(Fixture.objects.exists() or ClubMember.objects.exists())


class MembersTests(Base):
    def test_the_coach_adds_any_student_and_names_a_captain(self):
        found = self.coach.get(f"{CLUBS}{self.club.id}/candidates/", {"q": "cat"}).data
        self.assertEqual([r["name"] for r in found], ["Cate K"])
        self.assertEqual(self.coach.get(f"{CLUBS}{self.club.id}/candidates/", {"q": "c"}).data, [])
        response = self.coach.post(f"{CLUBS}{self.club.id}/members/", {"students": [self.cate.id, self.amina.id]}, format="json")
        self.assertEqual(response.data, {"added": 1, "already": 1})
        response = self.coach.patch(f"{CLUBS}{self.club.id}/members/{self.cate.id}/", {"role": "Captain"}, format="json")
        self.assertEqual(response.data["role"], "Captain")
        rows = self.coach.get(f"{CLUBS}{self.club.id}/members/").data
        self.assertEqual([(r["name"], r["role"]) for r in rows], [("Amina K", ""), ("Ben K", ""), ("Cate K", "Captain")])

    def test_other_teachers_see_only_their_own_pupils_in_a_club(self):
        rows = self.client_a.get(f"{CLUBS}{self.club.id}/members/").data  # user_a teaches 2 East (Amina)
        self.assertEqual([r["name"] for r in rows], ["Amina K"])
        self.assertEqual(self.client_a.post(f"{CLUBS}{self.club.id}/members/", {"students": [self.cate.id]},
                                            format="json").status_code, 403)
        self.assertEqual(self.client_a.get(f"{CLUBS}{self.club.id}/candidates/", {"q": "cate"}).status_code, 403)

    def test_only_students_of_this_school(self):
        other = Student.objects.create(school=self.school_b, first_name="Zed", last_name="B")
        self.assertEqual(self.coach.post(f"{CLUBS}{self.club.id}/members/", {"students": [other.id]},
                                         format="json").status_code, 400)
        self.assertEqual(self.coach.get(f"{CLUBS}{self.club.id}/candidates/", {"q": "zed"}).data, [])

    def test_leaving_drops_them_from_squads_still_to_come(self):
        upcoming = self.fixture(players=[self.ben.id]).data["id"]
        self.assertEqual(self.coach.delete(f"{CLUBS}{self.club.id}/members/{self.ben.id}/").status_code, 204)
        self.assertEqual(list(Fixture.objects.get(pk=upcoming).players.all()), [])
        self.assertEqual(self.coach.delete(f"{CLUBS}{self.club.id}/members/{self.ben.id}/").status_code, 400)


class RegisterTests(Base):
    def test_taking_and_correcting_a_register(self):
        url = f"{CLUBS}{self.club.id}/register/"
        blank = self.coach.get(url).data
        self.assertEqual((blank["taken"], [s["status"] for s in blank["students"]]), (False, [None, None]))
        body = {"date": self.today.isoformat(), "note": "Training in the hall",
                "marks": [{"student": self.amina.id, "status": "present"}, {"student": self.ben.id, "status": "absent"}]}
        saved = self.coach.post(url, body, format="json").data
        self.assertEqual([(s["name"], s["status"]) for s in saved["students"]], [("Amina K", "present"), ("Ben K", "absent")])
        body["marks"][1]["status"] = "excused"
        self.coach.post(url, body, format="json")
        self.assertEqual((ClubSession.objects.count(), ClubAttendance.objects.get(student=self.ben).status), (1, "excused"))
        sessions = self.coach.get(f"{CLUBS}{self.club.id}/sessions/").data
        self.assertEqual((sessions[0]["present"], sessions[0]["excused"]), (1, 1))
        members = {r["name"]: r["attendance"] for r in self.coach.get(f"{CLUBS}{self.club.id}/members/").data}
        self.assertEqual(members["Amina K"]["present"], 1)
        entry = ActivityLog.objects.filter(action="clubs.register_taken").order_by("id").first()
        self.assertIn("1 of 2 present", entry.summary)
        self.assertNotIn("hall", entry.summary)

    def test_bad_registers(self):
        url = f"{CLUBS}{self.club.id}/register/"
        tomorrow = (self.today + timedelta(days=1)).isoformat()
        good = [{"student": self.amina.id, "status": "present"}]
        self.assertEqual(self.coach.post(url, {"date": tomorrow, "marks": good}, format="json").status_code, 400)
        self.assertEqual(self.coach.post(url, {"date": "soon", "marks": good}, format="json").status_code, 400)
        self.assertEqual(self.coach.post(url, {"date": self.today.isoformat(), "marks": []}, format="json").status_code, 400)
        for marks in ([{"student": self.cate.id, "status": "present"}], [{"student": self.amina.id, "status": "late"}]):
            self.assertEqual(self.coach.post(url, {"date": self.today.isoformat(), "marks": marks}, format="json").status_code, 400)
        self.assertEqual(self.client_a.get(url).status_code, 403)
        self.assertEqual(self.client_a.post(url, {"date": self.today.isoformat(), "marks": good}, format="json").status_code, 403)


class FixtureTests(Base):
    def test_a_fixture_then_its_result(self):
        response = self.fixture(players=[self.amina.id, self.ben.id])
        self.assertEqual(response.status_code, 201, response.data)
        fid = response.data["id"]
        self.assertEqual(self.client_a.get(FIXTURES, {"upcoming": 1}).data[0]["opponent"], "St Mary's")
        self.assertEqual(self.client_a.get(FIXTURES, {"results": 1}).data, [])
        response = self.coach.patch(f"{FIXTURES}{fid}/", {"our_score": 3, "their_score": 1, "report": "A great win."}, format="json")
        self.assertEqual(response.data["outcome"], "win")
        self.assertEqual(self.client_a.get(FIXTURES, {"results": 1}).data[0]["outcome"], "win")
        self.assertTrue(ActivityLog.objects.filter(action="clubs.fixture_updated", summary__contains="the result of").exists())

    def test_a_result_in_words(self):
        fid = self.fixture(opponent="County cross-country").data["id"]
        response = self.coach.patch(f"{FIXTURES}{fid}/", {"result_note": "3rd of 12 schools"}, format="json")
        self.assertIsNone(response.data["outcome"])
        self.assertEqual(len(self.coach.get(FIXTURES, {"results": 1}).data), 1)

    def test_bad_fixtures(self):
        self.assertEqual(self.fixture(players=[self.cate.id]).status_code, 400)  # not in the club
        self.assertEqual(self.fixture(our_score=2).status_code, 400)  # one score only
        self.assertEqual(self.fixture(opponent=" ").status_code, 400)
        self.assertEqual(self.fixture(club=999999).status_code, 400)
        self.assertEqual(self.client_a.post(FIXTURES, {"club": self.club.id, "date": self.today.isoformat(),
                                                       "opponent": "X"}, format="json").status_code, 403)
        fid = self.fixture().data["id"]
        self.assertEqual(self.client_a.patch(f"{FIXTURES}{fid}/", {"our_score": 1, "their_score": 0}, format="json").status_code, 403)
        self.assertEqual(self.client_a.delete(f"{FIXTURES}{fid}/").status_code, 403)
        self.assertEqual(self.coach.delete(f"{FIXTURES}{fid}/").status_code, 204)

    def test_other_teachers_see_only_their_own_pupils_in_a_squad(self):
        self.fixture(players=[self.amina.id, self.ben.id])
        self.assertEqual([p["name"] for p in self.client_a.get(FIXTURES).data[0]["players"]], ["Amina K"])
        self.assertEqual(len(self.coach.get(FIXTURES).data[0]["players"]), 2)


class ParentTests(Base):
    def test_parents_see_their_childs_clubs_attendance_and_fixtures(self):
        self.coach.post(f"{CLUBS}{self.club.id}/register/", {"date": self.today.isoformat(), "note": "Staff note",
                        "marks": [{"student": self.amina.id, "status": "present"}]}, format="json")
        self.fixture(players=[self.amina.id])
        past = Fixture.objects.create(club=self.club, date=self.today - timedelta(days=2), opponent="Hill School",
                                      our_score=1, their_score=1, report="Hard-fought draw.")
        past.players.add(self.ben)
        clubs = self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/").data["clubs"]
        (club,) = clubs
        self.assertEqual((club["name"], club["meets"], club["leaders"]), ("Football", "Tuesdays 3:30pm", ["coach"]))
        self.assertEqual(club["attendance"]["present"], 1)
        self.assertEqual([(f["opponent"], f["selected"]) for f in club["upcoming"]], [("St Mary's", True)])
        (result,) = club["results"]
        self.assertEqual((result["outcome"], result["selected"]), ("draw", False))
        self.assertNotIn("report", result)  # the match report is for the squad's families
        self.assertNotIn("Staff note", str(clubs))
        self.assertNotIn("Ben", str(clubs))

    def test_parents_and_the_public_cannot_use_the_staff_api(self):
        for url in (CLUBS, FIXTURES, f"{CLUBS}{self.club.id}/members/"):
            self.assertEqual(self.parent.get(url).status_code, 403)
            self.assertEqual(APIClient().get(url).status_code, 401)


class IsolationTests(Base):
    def setUp(self):
        super().setUp()
        self.make_admin(self.user_b)
        self.fid = self.fixture(players=[self.amina.id]).data["id"]

    def test_another_schools_admin_reaches_nothing(self):
        c = self.client_b
        self.assertEqual(c.get(CLUBS).data, [])
        self.assertEqual(c.get(FIXTURES).data, [])
        for url in (f"{CLUBS}{self.club.id}/", f"{CLUBS}{self.club.id}/members/", f"{CLUBS}{self.club.id}/register/",
                    f"{CLUBS}{self.club.id}/sessions/", f"{FIXTURES}{self.fid}/"):
            self.assertEqual(c.get(url).status_code, 404, url)
        self.assertEqual(c.patch(f"{CLUBS}{self.club.id}/", {"name": "Hacked"}, format="json").status_code, 404)
        self.assertEqual(c.delete(f"{FIXTURES}{self.fid}/").status_code, 404)
        self.assertEqual(c.post(f"{CLUBS}{self.club.id}/members/", {"students": [self.cate.id]}, format="json").status_code, 404)
        self.assertEqual(c.post(FIXTURES, {"club": self.club.id, "date": self.today.isoformat(), "opponent": "X"},
                                format="json").status_code, 400)
        self.assertEqual(Club.objects.get().name, "Football")

    def test_governors_are_kept_out(self):
        gov = self.staff("gov@alpha.test", "governor")[1]
        self.assertEqual(gov.get(CLUBS).status_code, 403)
        self.assertEqual(gov.get(FIXTURES).status_code, 403)


class PrivacyAndProfileTests(Base):
    def test_profile_export_and_erasure(self):
        from students.privacy import family_export, family_export_data, remove_personal_data

        self.coach.post(f"{CLUBS}{self.club.id}/register/", {"date": self.today.isoformat(),
                        "marks": [{"student": self.amina.id, "status": "present"}]}, format="json")
        fid = self.fixture(players=[self.amina.id]).data["id"]
        profile = self.client_a.get(f"/api/students/{self.amina.id}/profile/").data
        self.assertEqual(profile["clubs"], [{"id": self.club.id, "name": "Football", "role": ""}])
        self.assertTrue(family_export(self.amina))
        data = family_export_data(self.amina)["clubs"]
        self.assertEqual((len(data["memberships"]), len(data["registers"]), len(data["picked_for"])), (1, 1, 1))
        counts = remove_personal_data(self.amina, self.admin_a)
        self.assertEqual(counts["club_records_deleted"], 2)
        self.assertFalse(Fixture.objects.get(pk=fid).players.exists())


class DemoTests(Base):
    def test_demo_clubs_are_filled_once(self):
        from .demo import fill_demo

        for n in range(25):
            self.pupil(f"Demo{n}", self.c2w)
        Club.objects.all().delete()
        self.assertEqual(fill_demo(self.school_a), 7)
        self.assertEqual(fill_demo(self.school_a), 0)
        football = Club.objects.get(name="Football")
        self.assertTrue(football.fixtures.filter(our_score__isnull=False).exists())
        self.assertTrue(football.leaders.exists())
        self.assertEqual(football.sessions.count(), 6)
