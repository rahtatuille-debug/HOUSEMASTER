"""
H: an isolation sweep over the modules added since the last audit (timetable, boarding, leave, sick bay, support
plans, rankings). Another school, a teacher outside a class or house, a parent of another child, and the public
must reach nothing they shouldn't. Admissions has its own sweep (admissions.test_fixes.AdmissionsIsolationTests).
"""
from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from boarding.models import Bed, BoardingHouse, Dorm, LeaveRequest, RollCall, SickBayVisit
from gradebook.models import Grade, Subject, Term
from guardians.models import Guardian
from students.models import School, SchoolClass, Student, YearGroup
from support.models import SupportConcern
from timetable.models import Lesson, Period, Room


class SweepFixture(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        School.objects.filter(pk__in=[self.school_a.pk, self.school_b.pk]).update(has_boarding=True)
        self.school_a.refresh_from_db()
        self.admin = self.authed_client(self.admin_a)
        self.make_admin(self.user_b)  # client_b: another school's admin
        year = YearGroup.objects.create(school=self.school_a, name="Form 2")
        self.mine = SchoolClass.objects.create(year_group=year, name="2 East")   # user_a teaches it
        self.theirs = SchoolClass.objects.create(year_group=year, name="2 West")  # nobody here teaches it
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.assign(self.user_a, self.mine, self.maths)
        self.teacher = self.authed_client(self.user_a)  # not boarding staff
        self.term = Term.objects.create(school=self.school_a, name="T1", start_date=date(2026, 1, 5),
                                        end_date=date(2026, 4, 3))
        self.house = BoardingHouse.objects.create(school=self.school_a, name="Uhuru House")
        self.bed = Bed.objects.create(dorm=Dorm.objects.create(house=self.house, name="Dorm A"), name="Bed 1")
        self.amina = Student.objects.create(school=self.school_a, first_name="Amina", last_name="K",
                                            school_class=self.mine, mode_of_learning="boarding")
        self.ben = Student.objects.create(school=self.school_a, first_name="Ben", last_name="K",
                                          school_class=self.theirs, mode_of_learning="boarding")
        self.bed.student = self.amina
        self.bed.save()
        for s, score in ((self.amina, 30), (self.ben, 20)):
            for _ in range(3):
                Grade.objects.create(student=s, subject=self.maths, term=self.term, score=score)
        self.leave = LeaveRequest.objects.create(school=self.school_a, student=self.ben, status="requested",
                                                 leaving_at=timezone.now() + timedelta(days=1),
                                                 returning_at=timezone.now() + timedelta(days=2), reason="Wedding")
        self.visit = SickBayVisit.objects.create(school=self.school_a, student=self.ben, complaint="Headache",
                                                 checked_in_at=timezone.now())
        self.roll = RollCall.objects.create(house=self.house, date=timezone.localdate(), session="evening")
        self.concern = SupportConcern.objects.create(school=self.school_a, student=self.ben, status="open",
                                                     note="Private note about Ben")
        period = Period.objects.create(school=self.school_a, name="Lesson 1", start_time=time(8), end_time=time(8, 40))
        self.room = Room.objects.create(school=self.school_a, name="Lab 1")
        self.lesson = Lesson.objects.create(school=self.school_a, school_class=self.theirs, subject=self.maths,
                                            day=1, period=period, room=self.room)
        parent = User.objects.create_user(username="pa@alpha.test", email="pa@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)
        self.parent = self.authed_client(parent)  # Amina's parent, not Ben's
        self.anon = APIClient()


class OtherSchoolTests(SweepFixture):
    def test_lists_show_nothing_from_another_school(self):
        for url in ("/api/boarding/houses/", "/api/boarding/roll-calls/", "/api/boarding/leave/",
                    "/api/boarding/sick-bay/", "/api/support/concerns/", "/api/timetable/lessons/",
                    "/api/timetable/periods/", "/api/timetable/rooms/", "/api/boarding/boarders/"):
            response = self.client_b.get(url)
            self.assertEqual(response.status_code, 200, url)
            rows = response.data["results"] if isinstance(response.data, dict) and "results" in response.data \
                else response.data
            self.assertEqual(len(rows), 0, url)
        self.assertEqual(self.client_b.get("/api/boarding/students/", {"q": "Amina"}).data, [])
        self.assertEqual(self.client_b.get("/api/boarding/overview/").data["boarders"], 0)
        names = str(self.client_b.get("/api/support/suggestions/").data)
        self.assertNotIn("Ben", names)

    def test_another_schools_records_cannot_be_opened_or_changed(self):
        cases = [("get", f"/api/boarding/houses/{self.house.id}/"), ("get", f"/api/boarding/roll-calls/{self.roll.id}/"),
                 ("get", f"/api/boarding/leave/{self.leave.id}/"), ("post", f"/api/boarding/leave/{self.leave.id}/approve/"),
                 ("get", f"/api/boarding/sick-bay/{self.visit.id}/"), ("get", f"/api/support/concerns/{self.concern.id}/"),
                 ("post", f"/api/support/concerns/{self.concern.id}/resolve/"), ("get", f"/api/timetable/lessons/{self.lesson.id}/"),
                 ("delete", f"/api/timetable/lessons/{self.lesson.id}/"), ("patch", f"/api/timetable/rooms/{self.room.id}/")]
        for method, url in cases:
            self.assertIn(getattr(self.client_b, method)(url, {}, format="json").status_code, (403, 404), url)
        self.assertIn(self.client_b.post(f"/api/boarding/beds/{self.bed.id}/", {"student": None}, format="json")
                      .status_code, (403, 404))
        self.bed.refresh_from_db()
        self.leave.refresh_from_db()
        self.concern.refresh_from_db()
        self.assertEqual((self.bed.student, self.leave.status, self.concern.status), (self.amina, "requested", "open"))
        self.assertTrue(Lesson.objects.filter(pk=self.lesson.pk).exists())

    def test_another_schools_classes_and_rankings_cannot_be_used(self):
        self.assertIn(self.client_b.get("/api/timetable/week/", {"school_class": self.mine.id}).status_code, (400, 403, 404))
        self.assertIn(self.client_b.get("/api/analytics/performance/", {"scope": "class", "id": self.mine.id})
                      .status_code, (403, 404))
        data = self.client_b.get("/api/analytics/performance/", {"scope": "school"}).data
        self.assertNotIn("Amina", str(data))
        their_period = Period.objects.create(school=self.school_b, name="P", start_time=time(8), end_time=time(9))
        response = self.client_b.post("/api/timetable/lessons/", {"school_class": self.mine.id, "title": "X", "day": 1,
                                                                  "period": their_period.id}, format="json")
        self.assertEqual(response.status_code, 400)


class TeacherScopeTests(SweepFixture):
    def test_a_teacher_who_is_not_boarding_staff_reaches_no_boarding_records(self):
        for url in ("/api/boarding/houses/", "/api/boarding/leave/", "/api/boarding/sick-bay/",
                    "/api/boarding/roll-calls/", "/api/boarding/overview/", "/api/boarding/boarders/"):
            self.assertEqual(self.teacher.get(url).status_code, 403, url)

    def test_a_teacher_sees_support_and_rankings_only_for_their_classes(self):
        concerns = self.teacher.get("/api/support/concerns/").data
        rows = concerns["results"] if isinstance(concerns, dict) else concerns
        self.assertNotIn(self.concern.id, [c["id"] for c in rows])
        self.assertNotIn("Ben", str(self.teacher.get("/api/support/suggestions/").data))
        self.assertIn(self.teacher.get("/api/analytics/performance/", {"scope": "class", "id": self.theirs.id})
                      .status_code, (403, 404))
        self.assertIsNone(self.teacher.get("/api/analytics/performance/", {"scope": "school"}).data.get("students"))

    def test_a_teacher_cannot_change_the_timetable_or_boarding_set_up(self):
        self.assertEqual(self.teacher.post("/api/timetable/rooms/", {"name": "Hall"}, format="json").status_code, 403)
        self.assertEqual(self.teacher.delete(f"/api/timetable/lessons/{self.lesson.id}/").status_code, 403)
        self.assertEqual(self.teacher.patch("/api/timetable/school-week/", {"days": [1]}, format="json").status_code, 403)
        self.assertEqual(self.teacher.post("/api/boarding/houses/", {"name": "New"}, format="json").status_code, 403)


class GuardianTests(SweepFixture):
    def test_a_parent_sees_only_their_own_childs_boarding_and_nothing_staff_only(self):
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.ben.id}/boarding/").status_code, 404)
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.ben.id}/timetable/").status_code, 404)
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.ben.id}/term-summary/",
                                         {"term": self.term.id}).status_code, 404)
        self.assertEqual(self.parent.post(f"/api/guardian-students/{self.ben.id}/leave-requests/{self.leave.id}/cancel/")
                         .status_code, 404)
        own = self.parent.get(f"/api/guardian-students/{self.amina.id}/boarding/")
        self.assertEqual(own.status_code, 200)
        self.assertNotIn("Wedding", str(own.data))  # Ben's leave
        self.assertNotIn("Headache", str(own.data))  # Ben's sick bay visit
        for url in ("/api/boarding/houses/", "/api/boarding/leave/", "/api/support/concerns/", "/api/support/suggestions/",
                    "/api/timetable/lessons/", "/api/analytics/performance/"):
            self.assertEqual(self.parent.get(url).status_code, 403, url)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, "requested")

    def test_a_parent_never_sees_another_childs_support_note(self):
        profile = self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/")
        self.assertNotIn("Private note about Ben", str(profile.data))


class PublicTests(SweepFixture):
    def test_nothing_is_open_to_the_public(self):
        for url in ("/api/boarding/houses/", "/api/boarding/overview/", "/api/boarding/leave/", "/api/boarding/sick-bay/",
                    "/api/support/concerns/", "/api/support/suggestions/", "/api/timetable/lessons/",
                    "/api/timetable/week/", "/api/analytics/performance/", f"/api/guardian-students/{self.amina.id}/boarding/"):
            self.assertEqual(self.anon.get(url).status_code, 401, url)
