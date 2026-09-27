"""Emails to parents when an announcement or report is published for them."""
from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings

from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from communications.models import Announcement
from gradebook.models import Term
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

from .models import Guardian


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class ParentNotificationTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Grade 7")
        other_year = YearGroup.objects.create(school=self.school_a, name="Grade 8")
        self.class_7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.class_7b = SchoolClass.objects.create(year_group=year, name="7B")
        self.class_8a = SchoolClass.objects.create(year_group=other_year, name="8A")
        self.term = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.kid_7a = self.child("Amina", self.class_7a)
        self.kid_7b = self.child("Brian", self.class_7b)
        self.kid_8a = self.child("Chege", self.class_8a)
        self.p_7a = self.parent("p7a@alpha.test", [self.kid_7a])
        self.p_7b = self.parent("p7b@alpha.test", [self.kid_7b])
        self.p_8a = self.parent("p8a@alpha.test", [self.kid_8a])
        self.opted_out = self.parent("quiet@alpha.test", [self.kid_7a], email_notifications=False)
        other_school_kid = Student.objects.create(school=self.school_b, first_name="Zed", last_name="B")
        self.parent("beta@beta.test", [other_school_kid], school=self.school_b)

    def child(self, name, school_class):
        return Student.objects.create(school=self.school_a, school_class=school_class, first_name=name,
                                      last_name="Test")

    def parent(self, email, kids, school=None, **extra):
        user = User.objects.create_user(username=email, email=email, password="pass1234")
        g = Guardian.objects.create(user=user, school=school or self.school_a, display_name=email.split("@")[0],
                                    **extra)
        g.students.set(kids)
        return g

    def publish(self, **fields):
        a = Announcement.objects.create(school=self.school_a, title="Sports day", body="Friday at 9am.",
                                        created_by=self.admin_a, **fields)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.admin_client.post(f"/api/announcements/{a.id}/publish/")
        self.assertEqual(response.status_code, 200)
        return sorted(m.to[0] for m in mail.outbox)

    def test_class_announcement_emails_only_that_classes_parents(self):
        self.assertEqual(self.publish(audience="school_class", school_class=self.class_7a), ["p7a@alpha.test"])
        self.assertIn("Friday at 9am.", mail.outbox[0].body)
        self.assertIn("Alpha Academy: Sports day", mail.outbox[0].subject)

    def test_year_group_and_whole_school_audiences(self):
        self.assertEqual(self.publish(audience="year_group", year_group=self.class_7a.year_group),
                         ["p7a@alpha.test", "p7b@alpha.test"])
        mail.outbox.clear()
        self.assertEqual(self.publish(audience="all_parents"), ["p7a@alpha.test", "p7b@alpha.test", "p8a@alpha.test"])
        self.assertTrue(ActivityLog.objects.filter(action="notification.emailed", summary__startswith="Emailed 3 of 3").exists())

    def test_staff_announcements_email_no_parents(self):
        self.assertEqual(self.publish(audience="all_staff"), [])

    def test_each_parent_gets_their_own_email(self):
        self.publish(audience="all_parents")
        self.assertTrue(all(len(m.to) == 1 and not m.cc and not m.bcc for m in mail.outbox))

    def test_deactivated_parents_get_nothing(self):
        self.p_7b.user.is_active = False
        self.p_7b.user.save()
        self.assertNotIn("p7b@alpha.test", self.publish(audience="all_parents"))

    def test_finalizing_a_report_tells_that_childs_parents_only(self):
        report = StudentReport.objects.create(student=self.kid_7a, term=self.term, progress_summary="Staff only",
                                              report_comment="Well done", status="submitted")
        with self.captureOnCommitCallbacks(execute=True):
            self.admin_client.post(f"/api/reports/{report.id}/finalize/")
        self.assertEqual([m.to[0] for m in mail.outbox], ["p7a@alpha.test"])
        self.assertIn("Amina's Term 1 2026 report is ready", mail.outbox[0].subject)
        self.assertNotIn("Staff only", mail.outbox[0].body)
        self.assertNotIn("Well done", mail.outbox[0].body)

    def test_finalizing_a_whole_class_emails_each_family(self):
        StudentReport.objects.create(student=self.kid_7a, term=self.term, progress_summary="x",
                                     report_comment="y", status="submitted")
        StudentReport.objects.create(student=self.kid_7b, term=self.term, progress_summary="x",
                                     report_comment="y", status="submitted")
        with self.captureOnCommitCallbacks(execute=True):
            self.admin_client.post("/api/reports/finalize-class/", {"school_class": self.class_7a.id,
                                                                   "term": self.term.id})
        self.assertEqual([m.to[0] for m in mail.outbox], ["p7a@alpha.test"])

    def test_parent_turns_emails_off_and_on(self):
        client = self.authed_client(self.p_7a.user)
        response = client.patch("/api/guardian-me/", {"email_notifications": False}, format="json")
        self.assertFalse(response.data["contact"]["email_notifications"])
        self.assertNotIn("p7a@alpha.test", self.publish(audience="all_parents"))
        self.assertTrue(ActivityLog.objects.filter(summary__contains="turned email notifications off").exists())

    def test_admin_cannot_change_a_parents_email_choice(self):
        self.admin_client.patch(f"/api/parents/{self.opted_out.id}/", {"email_notifications": True, "phone": ""},
                                format="json")
        self.opted_out.refresh_from_db()
        self.assertFalse(self.opted_out.email_notifications)

    def test_an_email_server_failure_does_not_undo_the_publish(self):
        from unittest.mock import patch
        with patch("django.core.mail.backends.locmem.EmailBackend.send_messages", side_effect=OSError("down")):
            self.publish(audience="all_parents")
        self.assertEqual(Announcement.objects.get().status, "published")
        self.assertTrue(ActivityLog.objects.filter(summary__startswith="Emailed 0 of 3").exists())

    def test_reserved_demo_addresses_are_skipped(self):
        self.parent("demo@school.example", [self.kid_7a])
        self.assertEqual(self.publish(audience="school_class", school_class=self.class_7a), ["p7a@alpha.test"])
