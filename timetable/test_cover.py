"""
Staff cover (owner's request, 2026-10-08): record an absent teacher and see
their lessons that need cover that day, with who is free; arrange cover.
Admins and leadership only; the cover teacher sees it on their day.
"""
from datetime import date, time

from accounts.models import StaffRole
from accounts.test_roles import RoleFixture
from activity.models import ActivityLog

from . import cover
from .models import CoverAssignment, Lesson, Period, StaffAbsence

MONDAY = date(2026, 10, 12)
COVER = "/api/timetable/cover/"
ABSENCES = "/api/timetable/absences/"


class CoverTests(RoleFixture):
    def setUp(self):
        super().setUp()
        self.p1 = Period.objects.create(school=self.school_a, name="Lesson 1", start_time=time(8), end_time=time(8, 40))
        self.p2 = Period.objects.create(school=self.school_a, name="Lesson 2", start_time=time(8, 40), end_time=time(9, 20))
        self.t1 = self.user_a.profile                       # away
        self.t2 = self.maths_3e[0].profile                  # busy in Lesson 1
        self.t3_user, _ = self.staff("free@alpha.test")     # free in Lesson 1, teaches Lesson 2
        self.t3 = self.t3_user.profile
        self.l1 = Lesson.objects.create(school=self.school_a, school_class=self.c2e, subject=self.maths, teacher=self.t1,
                                        day=1, period=self.p1)
        self.l2 = Lesson.objects.create(school=self.school_a, school_class=self.c2e, subject=self.maths, teacher=self.t1,
                                        day=1, period=self.p2)
        Lesson.objects.create(school=self.school_a, school_class=self.c3e, subject=self.maths, teacher=self.t2,
                              day=1, period=self.p1)
        Lesson.objects.create(school=self.school_a, school_class=self.c3e, subject=self.english, teacher=self.t3,
                              day=1, period=self.p2)
        _, self.lead = self.staff("lead@alpha.test", "teacher", StaffRole.Role.LEADERSHIP)

    def away(self, client=None, **extra):
        body = {"teacher": self.t1.id, "start_date": MONDAY.isoformat(), "end_date": MONDAY.isoformat(),
                "reason": "sick", "note": "Flu, back Wednesday", **extra}
        return (client or self.lead).post(ABSENCES, body, format="json")

    def test_recording_an_absence_lists_their_lessons_and_who_is_free(self):
        self.assertEqual(self.away().status_code, 201)
        day = self.lead.get(COVER, {"date": MONDAY.isoformat()}).data
        self.assertTrue(day["school_day"])
        self.assertEqual([(r["id"], r["why"]) for r in day["lessons"]], [(self.l1.id, "Sick"), (self.l2.id, "Sick")])
        free_p1 = [f["name"] for f in day["lessons"][0]["free"]]
        self.assertIn(self.t3.name, free_p1)
        self.assertNotIn(self.t2.name, free_p1)  # teaching then
        self.assertNotIn(self.t1.name, free_p1)  # away
        self.assertNotIn(self.t3.name, [f["name"] for f in day["lessons"][1]["free"]])  # teaching Lesson 2
        self.assertEqual(day["absent"][0]["reason"], "Sick")
        self.assertIn(self.t3.name, [p["name"] for p in day["staff"]])

    def test_arranging_cover_and_the_cover_teachers_day(self):
        self.away()
        response = self.lead.post(COVER, {"lesson": self.l1.id, "date": MONDAY.isoformat(), "cover_teacher": self.t3.id,
                                          "note": "Worksheet on the desk"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["covered"], response.data["total"]), (1, 2))
        mine = cover.my_cover(self.t3, MONDAY)
        self.assertEqual([(r["class_name"], r["cover_for"], r["note"]) for r in mine],
                         [("2 East", self.t1.name, "Worksheet on the desk")])
        # Now busy in Lesson 1, so not offered for another lesson then.
        self.assertNotIn(self.t3.id, [f["id"] for f in cover.free_staff(self.school_a, MONDAY, self.p1.id)])

    def test_someone_busy_or_away_cant_cover(self):
        self.away()
        busy = self.lead.post(COVER, {"lesson": self.l1.id, "date": MONDAY.isoformat(), "cover_teacher": self.t2.id},
                              format="json")
        self.assertEqual(busy.status_code, 400)
        self.assertIn("isn't free", str(busy.data))
        self.assertFalse(CoverAssignment.objects.exists())

    def test_a_lesson_whose_teacher_is_in_needs_no_cover(self):
        response = self.lead.post(COVER, {"lesson": self.l1.id, "date": MONDAY.isoformat(), "cover_teacher": self.t3.id},
                                  format="json")
        self.assertEqual(response.status_code, 400)

    def test_away_for_some_periods_only(self):
        self.assertEqual(self.away(periods=[self.p2.id]).status_code, 201)
        day = self.lead.get(COVER, {"date": MONDAY.isoformat()}).data
        self.assertEqual([r["id"] for r in day["lessons"]], [self.l2.id])
        self.assertEqual(self.away(periods=[self.p1.id], end_date="2026-10-13").status_code, 400)

    def test_removing_the_absence_removes_its_cover(self):
        absence_id = self.away().data["id"]
        self.lead.post(COVER, {"lesson": self.l1.id, "date": MONDAY.isoformat(), "cover_teacher": self.t3.id},
                       format="json")
        self.assertEqual(self.lead.delete(f"{ABSENCES}{absence_id}/").status_code, 204)
        self.assertFalse(CoverAssignment.objects.exists())

    def test_the_note_stays_out_of_the_log(self):
        self.away()
        self.assertTrue(ActivityLog.objects.filter(action="timetable.absence").exists())
        self.assertFalse(ActivityLog.objects.filter(summary__icontains="Flu").exists())

    def test_only_admins_and_leadership(self):
        self.assertEqual(self.away(client=self.client_a).status_code, 403)
        self.assertEqual(self.client_a.get(COVER).status_code, 403)
        self.assertEqual(self.away(client=self.admin).status_code, 201)
        self.assertIs(self.client_a.get("/api/me/").data["permissions"]["manage_cover"], False)

    def test_another_school_reaches_nothing(self):
        self.away()
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get(ABSENCES).data, [])
        self.assertEqual(self.client_b.post(COVER, {"lesson": self.l1.id, "date": MONDAY.isoformat()},
                                            format="json").status_code, 404)
        bad = self.client_b.post(ABSENCES, {"teacher": self.t1.id, "start_date": "2026-10-12", "end_date": "2026-10-12"},
                                 format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(StaffAbsence.objects.count(), 1)

    def test_a_weekend(self):
        self.assertFalse(self.lead.get(COVER, {"date": "2026-10-10"}).data["school_day"])
