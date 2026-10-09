"""
Parents and absences (owner's request, 2026-10-09): parents hear the same day
when their child is marked absent, and can tell the school about an absence,
which then shows on the register.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings

from accounts.models import StaffRole
from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import SchoolClass, Student, YearGroup

from .models import AbsenceAlert, AbsenceReport


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False,
                   FRONTEND_URL="https://app.housemaster.test")
class Base(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.today = school_localdate(self.school_a)
        year = YearGroup.objects.create(school=self.school_a, name="Form 2")
        self.east = SchoolClass.objects.create(year_group=year, name="2 East")
        self.west = SchoolClass.objects.create(year_group=year, name="2 West")
        self.amina = Student.objects.create(school=self.school_a, first_name="Amina", last_name="K", school_class=self.east)
        self.ben = Student.objects.create(school=self.school_a, first_name="Ben", last_name="O", school_class=self.west)
        parent = User.objects.create_user(username="pat", email="pat@parents.test", password="pass1234")
        self.parent = Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat Parent")
        self.parent.students.add(self.amina)
        self.parent_client = self.authed_client(parent)
        StaffRole.objects.create(profile=self.user_a.profile, role=StaffRole.Role.CLASS_TEACHER, school_class=self.east)
        self.admin = self.authed_client(self.admin_a)

    def mark(self, student, status, day=None, client=None):
        client = client or self.admin
        day = day or self.today
        existing = AttendanceRecord.objects.filter(student=student, date=day).first()
        with self.captureOnCommitCallbacks(execute=True):
            if existing:
                response = client.patch(f"/api/attendance/{existing.id}/", {"status": status}, format="json")
            else:
                response = client.post("/api/attendance/", {"student": student.id, "date": day.isoformat(),
                                                            "status": status}, format="json")
        self.assertIn(response.status_code, (200, 201), response.data)
        return response

    def report(self, start, end=None, reason="illness", details="Fever since last night", client=None):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.parent_client).post(
                f"/api/guardian-students/{self.amina.id}/absences/",
                {"start_date": start.isoformat(), "end_date": (end or start).isoformat(), "reason": reason,
                 "details": details}, format="json")


class AlertTests(Base):
    def test_marked_absent_today_tells_the_parents_once(self):
        self.mark(self.amina, "absent")
        (email,) = mail.outbox
        self.assertEqual(email.to, ["pat@parents.test"])
        self.assertIn("Amina was marked absent today", email.subject)
        self.assertIn(f"https://app.housemaster.test/?absence={self.amina.id}&date={self.today.isoformat()}", email.body)
        self.mark(self.amina, "present")  # a correction...
        self.mark(self.amina, "absent")  # ...and absent again: no second alert
        self.assertEqual([m.subject for m in mail.outbox],
                         ["Amina was marked absent today", "Update: Amina is at school today"])
        self.assertEqual(AbsenceAlert.objects.count(), 1)

    def test_no_alert_for_present_late_excused_or_another_day(self):
        self.mark(self.amina, "late")
        self.mark(self.ben, "present")
        self.mark(self.amina, "absent", day=self.today - timedelta(days=1))
        self.assertEqual(mail.outbox, [])

    def test_no_alert_when_a_parent_already_said(self):
        self.report(self.today)
        mail.outbox.clear()
        self.mark(self.amina, "absent")
        self.assertEqual(mail.outbox, [])

    def test_parents_who_turned_emails_off_get_a_push_only(self):
        self.parent.email_notifications = False
        self.parent.save(update_fields=["email_notifications"])
        with mock.patch("communications.push.send_to_users") as push:
            self.mark(self.amina, "absent")
        self.assertEqual(mail.outbox, [])
        (call,) = push.call_args_list
        self.assertEqual(call.args[0], [self.parent.user_id])
        self.assertNotIn("Amina", call.args[2])  # never a child's name in a push

    def test_the_school_can_turn_alerts_off(self):
        self.assertEqual(self.client_a.patch("/api/absences/settings/", {"alerts_enabled": False},
                                             format="json").status_code, 403)
        self.assertEqual(self.admin.patch("/api/absences/settings/", {"alerts_enabled": False},
                                          format="json").data, {"alerts_enabled": False})
        self.mark(self.amina, "absent")
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self.client_a.get("/api/absences/settings/").data, {"alerts_enabled": False})


class ReportTests(Base):
    def test_a_parent_reports_and_the_class_teacher_hears(self):
        response = self.report(self.today, self.today + timedelta(days=1))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["reason_label"], response.data["reported_by_name"]), ("Ill", "Pat Parent"))
        (email,) = mail.outbox
        self.assertEqual(email.to, ["teacher.a@alpha.test"])
        self.assertNotIn("Fever", email.body)  # the details stay in HouseMaster
        self.assertEqual(len(self.parent_client.get(f"/api/guardian-students/{self.amina.id}/absences/").data), 1)

    def test_the_details_are_never_logged(self):
        from activity.models import ActivityLog

        self.report(self.today)
        self.assertTrue(ActivityLog.objects.filter(action="absence.reported").exists())
        self.assertFalse(ActivityLog.objects.filter(summary__icontains="fever").exists())

    def test_dates_that_dont_make_sense(self):
        self.assertEqual(self.report(self.today, self.today - timedelta(days=1)).status_code, 400)
        self.assertEqual(self.report(self.today - timedelta(days=30)).status_code, 400)
        self.assertEqual(self.report(self.today + timedelta(days=200)).status_code, 400)
        self.assertEqual(self.report(self.today, self.today + timedelta(days=60)).status_code, 400)
        self.assertEqual(self.report(self.today).status_code, 201)
        self.assertEqual(self.report(self.today).status_code, 400)  # the same day twice

    def test_cancel(self):
        report_id = self.report(self.today).data["id"]
        url = f"/api/guardian-students/{self.amina.id}/absences/{report_id}/cancel/"
        self.assertIsNotNone(self.parent_client.post(url).data["cancelled_at"])
        self.assertEqual(self.parent_client.post(url).status_code, 404)
        self.assertEqual(self.report(self.today).status_code, 201)  # can report again

    def test_staff_see_reports_for_children_whose_register_they_see(self):
        self.report(self.today)
        rows = self.admin.get(f"/api/absence-reports/?date={self.today.isoformat()}").data
        self.assertEqual([(r["student_name"], r["details"]) for r in rows], [("Amina K", "Fever since last night")])
        # The class teacher of 2 East sees it; a teacher with no link to the class doesn't.
        self.assertEqual(len(self.client_a.get("/api/absence-reports/").data), 1)
        other = User.objects.create_user(username="t2", email="t2@alpha.test", password="pass1234")
        from accounts.models import Profile

        Profile.objects.create(user=other, school=self.school_a, role=Profile.Role.TEACHER)
        self.assertEqual(self.authed_client(other).get("/api/absence-reports/").data, [])
        # Another school never does.
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get("/api/absence-reports/").data, [])

    def test_seen(self):
        report_id = self.report(self.today).data["id"]
        self.assertEqual(len(self.admin.get("/api/absence-reports/?unseen=1").data), 1)
        self.assertIsNotNone(self.admin.post(f"/api/absence-reports/{report_id}/seen/").data["seen_at"])
        self.assertEqual(self.admin.get("/api/absence-reports/?unseen=1").data, [])
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.post(f"/api/absence-reports/{report_id}/seen/").status_code, 404)

    def test_only_this_childs_parents_and_never_a_student(self):
        stranger = User.objects.create_user(username="sam", email="sam@parents.test", password="pass1234")
        Guardian.objects.create(user=stranger, school=self.school_a, display_name="Sam").students.add(self.ben)
        self.assertEqual(self.report(self.today, client=self.authed_client(stranger)).status_code, 404)
        from studentaccounts.models import StudentAccount

        login = User.objects.create_user(username="amina.k", password="pass1234")
        StudentAccount.objects.create(user=login, student=self.amina, must_change_password=False)
        self.assertEqual(self.report(self.today, client=self.authed_client(login)).status_code, 403)
        self.assertEqual(AbsenceReport.objects.count(), 0)
