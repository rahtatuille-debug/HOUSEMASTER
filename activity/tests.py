"""
Tests for the activity log: who can read it, that it's scoped to one
school, and that the main actions actually write an entry.
"""
from accounts.models import Invite
from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Subject, Term
from students.models import Student

from .models import ActivityLog
from .services import log_activity


class ActivityLogAccessTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        log_activity(school=self.school_a, actor=self.admin_a, action="test.a", summary="A thing at A")
        log_activity(school=self.school_b, actor=self.user_b, action="test.b", summary="A thing at B")

    def test_admin_sees_only_own_schools_log(self):
        response = self.admin_client_a.get("/api/activity/")
        self.assertEqual(response.status_code, 200)
        summaries = [row["summary"] for row in response.data["results"]]
        self.assertIn("A thing at A", summaries)
        self.assertNotIn("A thing at B", summaries)

    def test_teacher_cannot_read_log(self):
        response = self.client_a.get("/api/activity/")
        self.assertEqual(response.status_code, 403)

    def test_log_is_read_only(self):
        entry = ActivityLog.objects.get(action="test.a")
        self.assertEqual(self.admin_client_a.post("/api/activity/", {}).status_code, 405)
        self.assertEqual(self.admin_client_a.delete(f"/api/activity/{entry.id}/").status_code, 405)

    def test_filter_by_action(self):
        log_activity(school=self.school_a, actor=self.admin_a, action="test.other", summary="Other")
        response = self.admin_client_a.get("/api/activity/", {"action": "test.other"})
        self.assertEqual([row["summary"] for row in response.data["results"]], ["Other"])

    def test_filter_by_category(self):
        log_activity(school=self.school_a, actor=self.admin_a, action="grade.updated", summary="G")
        log_activity(school=self.school_a, actor=self.admin_a, action="staff.deactivated", summary="S")
        log_activity(school=self.school_a, actor=self.admin_a, action="staff_invite.created", summary="I")
        response = self.admin_client_a.get("/api/activity/", {"category": "staff,staff_invite"})
        self.assertEqual({row["summary"] for row in response.data["results"]}, {"S", "I"})

    def test_actor_name_is_display_name_not_email(self):
        entry = ActivityLog.objects.get(action="test.a")
        self.assertNotIn("@", entry.actor_name)


class ActivityIsRecordedTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        self.student = Student.objects.create(school=self.school_a, first_name="Ada", last_name="Lovelace")
        self.subject = Subject.objects.create(school=self.school_a, name="Maths")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")

    def test_grade_change_records_old_and_new_score(self):
        grade = Grade.objects.create(student=self.student, subject=self.subject, term=self.term, score=60)
        response = self.admin_client_a.patch(f"/api/grades/{grade.id}/", {"score": "85"})
        self.assertEqual(response.status_code, 200)

        entry = ActivityLog.objects.get(action="grade.updated")
        self.assertEqual(entry.school, self.school_a)
        self.assertEqual(entry.actor, self.admin_a)
        self.assertIn("Ada Lovelace", entry.summary)
        self.assertEqual(entry.details["old"], "60.00/100.00")
        self.assertEqual(entry.details["new"], "85.00/100.00")

    def test_grade_delete_is_recorded(self):
        grade = Grade.objects.create(student=self.student, subject=self.subject, term=self.term, score=60)
        self.admin_client_a.delete(f"/api/grades/{grade.id}/")
        self.assertTrue(ActivityLog.objects.filter(action="grade.deleted", target_id=grade.id).exists())

    def test_attendance_change_is_recorded(self):
        record = AttendanceRecord.objects.create(student=self.student, date="2026-09-01", status="present")
        self.admin_client_a.patch(f"/api/attendance/{record.id}/", {"status": "absent"})
        entry = ActivityLog.objects.get(action="attendance.updated")
        self.assertEqual((entry.details["old"], entry.details["new"]), ("present", "absent"))

    def test_staff_invite_create_and_cancel_are_recorded(self):
        response = self.admin_client_a.post(
            "/api/invites/", {"email": "new@alpha.test", "name": "New Teacher", "role": "teacher"}
        )
        self.assertEqual(response.status_code, 201)
        self.admin_client_a.delete(f"/api/invites/{response.data['id']}/")
        actions = set(ActivityLog.objects.values_list("action", flat=True))
        self.assertTrue({"staff_invite.created", "staff_invite.cancelled"} <= actions)

    def test_accepting_an_invite_is_recorded_against_the_new_user(self):
        invite = Invite.objects.create(
            school=self.school_a, email="joiner@alpha.test", name="Joiner", invited_by=self.admin_a
        )
        response = self.client.post(
            "/api/invites/accept/", {"token": invite.token, "password": "a-long-Password-123", "accept_privacy": True}
        )
        self.assertEqual(response.status_code, 201)
        entry = ActivityLog.objects.get(action="staff_invite.accepted")
        self.assertEqual(entry.actor.email, "joiner@alpha.test")

    def test_password_reset_request_is_recorded(self):
        self.client.post("/api/password-reset/", {"email": self.user_a.email})
        entry = ActivityLog.objects.get(action="password.reset_requested")
        self.assertEqual(entry.school, self.school_a)
