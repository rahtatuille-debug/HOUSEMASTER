"""
Merits (owner's request, 2026-10-08): staff reward students next to
Behaviour, so a student's record isn't only incidents. Parents see shared
merits; the log never holds the reason.
"""
from datetime import timedelta

from rest_framework.test import APIClient

from activity.models import ActivityLog
from students.localtime import school_localdate
from students.models import Student

from .models import Merit
from .tests import Fixture

URL = "/api/discipline/merits/"
REASON = "Helped a new pupil find every classroom"


class MeritTests(Fixture):
    def give(self, client=None, **extra):
        body = {"student": self.amina.id, "category": "kindness", "points": 2, "reason": REASON, **extra}
        return (client or self.teacher).post(URL, body, format="json")

    def test_a_teacher_gives_a_merit_and_parents_see_it(self):
        response = self.give()
        self.assertEqual(response.status_code, 201, response.data)
        merit = Merit.objects.get()
        self.assertEqual((merit.student, merit.school, merit.points, merit.date, merit.shared_with_parents),
                         (self.amina, self.school_a, 2, school_localdate(self.school_a), True))
        self.assertEqual(response.data["category_label"], "Kindness and respect")
        rows = self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/").data["merits"]
        self.assertEqual([(r["reason"], r["points"]) for r in rows], [(REASON, 2)])

    def test_unshared_merits_stay_with_staff(self):
        self.give(shared_with_parents=False)
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/").data["merits"], [])

    def test_a_whole_class_at_once(self):
        cara = Student.objects.create(school=self.school_a, first_name="Cara", last_name="M", school_class=self.mine)
        response = self.teacher.post(URL, {"students": [self.amina.id, cara.id], "category": "effort"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["awarded"], 2)
        self.assertEqual(Merit.objects.filter(points=1).count(), 2)
        entry = ActivityLog.objects.get(action="discipline.merit_awarded")
        self.assertIn("2 students", entry.summary)

    def test_never_outside_the_teachers_classes(self):
        response = self.teacher.post(URL, {"students": [self.amina.id, self.ben.id], "category": "effort"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Merit.objects.exists())  # nobody gets it when one can't
        self.assertEqual(self.give(student=self.ben.id).status_code, 400)
        Merit.objects.create(school=self.school_a, student=self.ben, date=school_localdate(self.school_a), category="work")
        self.assertEqual(self.teacher.get(URL).data, [])
        self.assertEqual(len(self.admin.get(URL).data), 1)

    def test_bad_input(self):
        tomorrow = (school_localdate(self.school_a) + timedelta(days=1)).isoformat()
        self.assertEqual(self.give(date=tomorrow).status_code, 400)
        self.assertEqual(self.give(points=6).status_code, 400)
        self.assertEqual(self.give(points=0).status_code, 400)
        self.assertEqual(self.give(category="nonsense").status_code, 400)
        self.assertEqual(self.teacher.post(URL, {"students": [], "category": "effort"}, format="json").status_code, 400)
        self.assertEqual(self.teacher.post(URL, {"students": ["x"], "category": "effort"}, format="json").status_code, 400)
        self.assertEqual(self.teacher.post(URL, {"students": list(range(1, 202)), "category": "effort"},
                                           format="json").status_code, 400)

    def test_the_log_never_holds_the_reason(self):
        self.give()
        entry = ActivityLog.objects.get(action="discipline.merit_awarded")
        self.assertIn("Amina K", entry.summary)
        self.assertFalse(ActivityLog.objects.filter(summary__icontains="new pupil").exists())
        self.assertNotIn("new pupil", str(entry.details))

    def test_only_the_giver_or_leadership_changes_or_removes_it(self):
        theirs = Merit.objects.create(school=self.school_a, student=self.amina, category="work",
                                      date=school_localdate(self.school_a), awarded_by=self.admin_a)
        self.assertEqual(self.teacher.patch(f"{URL}{theirs.id}/", {"points": 3}, format="json").status_code, 403)
        self.assertEqual(self.teacher.delete(f"{URL}{theirs.id}/").status_code, 403)
        mine = self.give().data["id"]
        self.assertTrue(self.teacher.get(f"{URL}{mine}/").data["can_edit"])
        self.assertEqual(self.teacher.patch(f"{URL}{mine}/", {"points": 3, "student": self.ben.id},
                                            format="json").data["points"], 3)
        self.assertEqual(Merit.objects.get(pk=mine).student, self.amina)
        self.assertEqual(self.teacher.delete(f"{URL}{mine}/").status_code, 204)
        self.assertEqual(self.admin.delete(f"{URL}{theirs.id}/").status_code, 204)
        self.assertEqual(ActivityLog.objects.filter(action="discipline.merit_removed").count(), 2)

    def test_summary_and_profile(self):
        cara = Student.objects.create(school=self.school_a, first_name="Cara", last_name="M", school_class=self.mine)
        self.give(points=3)
        self.give(student=cara.id, points=1)
        Merit.objects.create(school=self.school_a, student=self.ben, date=school_localdate(self.school_a),
                             category="work", points=5)
        data = self.teacher.get(f"{URL}summary/").data
        self.assertEqual((data["points"], data["merits"], data["students"]), (4, 2, 2))
        self.assertEqual([(s["name"], s["points"]) for s in data["top_students"]], [("Amina K", 3), ("Cara M", 1)])
        self.assertEqual([(c["name"], c["points"]) for c in data["classes"]], [("2 East", 4)])
        school = self.admin.get(f"{URL}summary/").data
        self.assertEqual([c["name"] for c in school["classes"]], ["2 West", "2 East"])
        profile = self.teacher.get(f"/api/students/{self.amina.id}/profile/").data["merits"]
        self.assertEqual((profile["count"], profile["points"]), (1, 3))
        self.assertEqual(self.teacher.get(f"{URL}choices/").data["max_points"], 5)

    def test_filters(self):
        self.give()
        self.give(category="sport", date=(school_localdate(self.school_a) - timedelta(days=9)).isoformat())
        self.assertEqual(len(self.teacher.get(URL, {"category": "sport"}).data), 1)
        since = (school_localdate(self.school_a) - timedelta(days=2)).isoformat()
        self.assertEqual(len(self.teacher.get(URL, {"from": since}).data), 1)
        self.assertEqual(len(self.teacher.get(URL, {"school_class": self.mine.id}).data), 2)
        self.assertEqual(self.teacher.get(URL, {"to": "later"}).status_code, 400)


class MeritIsolationTests(Fixture):
    def setUp(self):
        super().setUp()
        self.merit = Merit.objects.create(school=self.school_a, student=self.ben, category="work", reason=REASON,
                                          date=school_localdate(self.school_a))
        self.make_admin(self.user_b)

    def test_another_school_reaches_nothing(self):
        self.assertEqual(self.client_b.get(URL).data, [])
        self.assertEqual(self.client_b.get(f"{URL}summary/").data["points"], 0)
        for method in ("get", "patch", "delete"):
            self.assertEqual(getattr(self.client_b, method)(f"{URL}{self.merit.id}/", {}, format="json").status_code, 404)
        self.assertEqual(self.client_b.post(URL, {"student": self.ben.id, "category": "work"},
                                            format="json").status_code, 400)

    def test_parents_and_the_public(self):
        self.assertEqual(self.parent.get(URL).status_code, 403)
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.ben.id}/profile/").status_code, 404)
        self.assertEqual(APIClient().get(URL).status_code, 401)


class MeritPrivacyTests(Fixture):
    def test_export_and_erasure(self):
        from students.privacy import family_export, family_export_data, remove_personal_data

        Merit.objects.create(school=self.school_a, student=self.amina, category="work", reason=REASON,
                             date=school_localdate(self.school_a))
        self.assertTrue(family_export(self.amina))
        self.assertEqual(family_export_data(self.amina)["merits"][0]["reason"], REASON)
        self.assertEqual(remove_personal_data(self.amina, self.admin_a)["merits_deleted"], 1)
        self.assertFalse(Merit.objects.exists())
