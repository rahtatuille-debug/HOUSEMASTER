"""
Students who need support: HouseMaster suggests them from warning signs
(low average, a big drop, poor attendance); a teacher confirms or dismisses
each one, or marks a student by hand. Parents see a confirmed concern, its
note and support plan, and get a short email; suggestions stay with staff.
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings

from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Subject, Term
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import School, SchoolClass, Student, YearGroup

from .models import SupportConcern

PLAN = "Extra maths practice on Tuesdays; please check homework each evening."


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class SupportTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        School.objects.filter(pk=self.school_a.pk).update(education_system="british", grading_scale="igcse9")
        self.school_a.refresh_from_db()
        self.admin = self.authed_client(self.admin_a)
        self.teacher = self.authed_client(self.user_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.c7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.c7b = SchoolClass.objects.create(year_group=year, name="7B")
        self.t1 = Term.objects.create(school=self.school_a, name="T1", start_date=date(2026, 1, 5),
                                      end_date=date(2026, 4, 3))
        self.t2 = Term.objects.create(school=self.school_a, name="T2", start_date=date(2026, 5, 4),
                                      end_date=date(2026, 8, 7))
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.assign(self.user_a, self.c7a, self.maths)

        self.low = self.pupil("Lowe", self.c7a, t2=30, t1=35)
        self.drop = self.pupil("Drop", self.c7a, t2=65, t1=80)
        self.absent = self.pupil("Abe", self.c7a, t2=70, t1=70, present=6)
        self.fine = self.pupil("Fine", self.c7a, t2=75, t1=74)
        self.other_class = self.pupil("Bee", self.c7b, t2=20, t1=20)

        parent_user = User.objects.create_user(username="p@alpha.test", email="p@alpha.test", password="x")
        self.parent_record = Guardian.objects.create(user=parent_user, school=self.school_a, display_name="Pat")
        self.parent_record.students.add(self.low)
        self.parent = self.authed_client(parent_user)

    def pupil(self, name, klass, t2, t1, present=10):
        s = Student.objects.create(school=self.school_a, first_name=name, last_name="K", school_class=klass)
        Grade.objects.create(student=s, subject=self.maths, term=self.t1, score=t1)
        Grade.objects.create(student=s, subject=self.maths, term=self.t2, score=t2)
        for day in range(10):
            AttendanceRecord.objects.create(student=s, date=date(2026, 5, 11) + timedelta(days=day),
                                            status="present" if day < present else "absent")
        return s

    def suggestions(self, client=None, **params):
        return {r["student"]: r for r in (client or self.admin).get(
            "/api/support/suggestions/", {"term": self.t2.id, **params}).data["results"]}

    def confirm(self, student, client=None, **extra):
        body = {"student": student.id, "term": self.t2.id, "reasons": ["low_average"],
                "note": "Finding fractions hard.", "support_plan": PLAN,
                "review_date": str(school_localdate(self.school_a) + timedelta(days=14)), **extra}
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.admin).post("/api/support/concerns/", body, format="json")

    # --- suggestions ---

    def test_warning_signs(self):
        found = self.suggestions()
        codes = {sid: {r["code"] for r in row["reasons"]} for sid, row in found.items()}
        self.assertEqual(codes[self.low.id], {"low_average"})
        self.assertEqual(codes[self.drop.id], {"big_drop"})
        self.assertEqual(codes[self.absent.id], {"poor_attendance"})
        self.assertNotIn(self.fine.id, found)
        self.assertIn("30", found[self.low.id]["reasons"][0]["label"])
        self.assertIn("60%", found[self.absent.id]["reasons"][0]["label"])

    def test_teachers_only_see_their_own_students(self):
        found = self.suggestions(self.teacher)
        self.assertIn(self.low.id, found)
        self.assertNotIn(self.other_class.id, found)

    def test_the_school_sets_the_limits(self):
        School.objects.filter(pk=self.school_a.pk).update(support_pass_mark=80, support_drop_points=50,
                                                          support_attendance_min=50)
        found = self.suggestions()
        self.assertIn(self.fine.id, found)  # 75 is now below the pass mark
        self.assertNotIn("big_drop", {r["code"] for r in found[self.drop.id]["reasons"]})
        self.assertNotIn("poor_attendance", {r["code"] for r in found[self.absent.id]["reasons"]})

    def test_admins_change_the_limits(self):
        response = self.admin.patch(f"/api/schools/{self.school_a.id}/", {"support_pass_mark": 50}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.support_pass_mark, 50)
        self.assertEqual(self.admin.patch(f"/api/schools/{self.school_a.id}/", {"support_pass_mark": 120},
                                          format="json").status_code, 400)

    # --- confirming ---

    def test_confirming_marks_the_student_and_tells_the_parent(self):
        response = self.confirm(self.low)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["parents_emailed"], 1)
        concern = SupportConcern.objects.get()
        self.assertEqual((concern.status, concern.source), ("open", "auto"))
        self.assertEqual([r["code"] for r in concern.reasons], ["low_average"])
        self.assertNotIn(self.low.id, self.suggestions())
        self.assertEqual([m.to for m in mail.outbox], [["p@alpha.test"]])
        self.assertNotIn("fractions", mail.outbox[0].body)  # details stay in the app
        self.assertNotIn(PLAN, mail.outbox[0].body)
        log = ActivityLog.objects.get(action="support.opened")
        self.assertNotIn("fractions", log.summary)

    def test_parent_who_turned_off_emails_is_not_emailed(self):
        Guardian.objects.filter(pk=self.parent_record.pk).update(email_notifications=False)
        self.assertEqual(self.confirm(self.low).data["parents_emailed"], 0)
        self.assertEqual(mail.outbox, [])

    def test_parents_see_a_confirmed_concern_but_never_a_suggestion(self):
        url = f"/api/guardian-students/{self.low.id}/profile/"
        self.assertIsNone(self.parent.get(url).data["support"])
        self.confirm(self.low)
        shown = self.parent.get(url).data["support"]
        self.assertEqual(shown["support_plan"], PLAN)
        self.assertEqual(shown["note"], "Finding fractions hard.")
        self.assertEqual([r["code"] for r in shown["reasons"]], ["low_average"])
        self.assertNotIn("review_date", shown)

    def test_dismissing_hides_the_suggestion_for_that_term(self):
        response = self.admin.post("/api/support/concerns/dismiss/",
                                   {"student": self.low.id, "term": self.t2.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn(self.low.id, self.suggestions())
        self.assertIsNone(self.parent.get(f"/api/guardian-students/{self.low.id}/profile/").data["support"])
        self.assertEqual(mail.outbox, [])

    def test_one_open_concern_per_student(self):
        self.confirm(self.low)
        self.assertEqual(self.confirm(self.low).status_code, 400)

    def test_marking_a_student_by_hand(self):
        response = self.confirm(self.fine, reasons=[], note="Struggling to settle after moving house.")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(SupportConcern.objects.get(student=self.fine).source, "manual")

    def test_unknown_reasons_are_refused(self):
        self.assertEqual(self.confirm(self.low, reasons=["bad_behaviour"]).status_code, 400)

    # --- following up ---

    def test_update_the_plan_and_resolve(self):
        concern_id = self.confirm(self.low).data["id"]
        response = self.admin.patch(f"/api/support/concerns/{concern_id}/", {"support_plan": "New plan"},
                                    format="json")
        self.assertEqual(response.data["support_plan"], "New plan")
        response = self.admin.post(f"/api/support/concerns/{concern_id}/resolve/", {"note": "Back on track."},
                                   format="json")
        self.assertEqual(response.data["status"], "resolved")
        self.assertIsNone(self.parent.get(f"/api/guardian-students/{self.low.id}/profile/").data["support"])

    def test_teacher_home_shows_suggestions_and_reviews_due(self):
        self.confirm(self.drop, client=self.teacher, review_date=str(school_localdate(self.school_a)))
        home = self.teacher.get("/api/teacher-home/").data["support"]
        self.assertEqual(home["suggested"], 2)  # Lowe and Abe; Drop is now confirmed
        self.assertEqual([d["student_name"] for d in home["due"]], ["Drop K"])

    def test_marked_in_lists(self):
        self.confirm(self.low)
        rows = {r["id"]: r for r in self.admin.get("/api/analytics/performance/",
                                                   {"scope": "class", "id": self.c7a.id, "term": self.t2.id}
                                                   ).data["students"]}
        self.assertEqual(rows[self.low.id]["support"], "open")
        self.assertEqual(rows[self.drop.id]["support"], "suggested")
        self.assertIsNone(rows[self.fine.id]["support"])
        students = {s["id"]: s for s in self.admin.get("/api/students/").data}
        self.assertTrue(students[self.low.id]["needs_support"])
        self.assertFalse(students[self.fine.id]["needs_support"])

    def test_staff_profile_shows_the_concern(self):
        self.confirm(self.low)
        data = self.admin.get(f"/api/students/{self.low.id}/profile/").data["support"]
        self.assertEqual(data["open"]["support_plan"], PLAN)
        self.assertEqual(len(data["history"]), 1)

    # --- who can ---

    def test_teachers_cannot_mark_students_they_do_not_teach(self):
        self.assertEqual(self.confirm(self.other_class, client=self.teacher).status_code, 400)

    def test_other_schools_and_parents_cannot_reach_it(self):
        concern_id = self.confirm(self.low).data["id"]
        admin_b = User.objects.create_user(username="ab@beta.test", email="ab@beta.test", password="x")
        from accounts.models import Profile
        Profile.objects.create(user=admin_b, school=self.school_b, role=Profile.Role.ADMIN)
        other = self.authed_client(admin_b)
        self.assertEqual(other.get(f"/api/support/concerns/{concern_id}/").status_code, 404)
        self.assertEqual(other.get("/api/support/suggestions/").data["results"], [])
        self.assertEqual(self.parent.get("/api/support/concerns/").status_code, 403)
        self.assertEqual(self.parent.get("/api/support/suggestions/").status_code, 403)

    # --- privacy tools ---

    def test_family_export_and_removal_include_support(self):
        from students.privacy import family_export_data, remove_personal_data

        self.confirm(self.low)
        exported = family_export_data(self.low)["support"]
        self.assertEqual(exported[0]["support_plan"], PLAN)
        remove_personal_data(self.low, self.admin_a)
        self.assertFalse(SupportConcern.objects.filter(student=self.low).exists())
