"""
F-16: the gaps in the family data tools, and retention.

The export now includes per-subject teacher comments and every
conversation about the child, and comes as JSON too. Removal also scrubs
the child's names from their subject comments and from conversations
about them, and deletes parent sign-up requests that named them.
apply_retention anonymises long-inactive students, off by default and a
dry run unless told otherwise.
"""
import json
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from gradebook.models import Subject, SubjectReport
from guardians.models import ParentSignupRequest
from messaging.models import Conversation, ConversationParticipant, Message
from students.models import Student

from .test_privacy import FamilyDataFixture


class DataSubjectToolingTests(FamilyDataFixture):
    def setUp(self):
        super().setUp()
        english = Subject.objects.create(school=self.school_a, name="English")
        SubjectReport.objects.create(student=self.kid, subject=english, term=self.term,
                                     comment="Amina reads widely; Amina Otieno should keep it up.")
        SubjectReport.objects.create(student=self.other, subject=english, term=self.term,
                                     comment="Cy writes clearly.")
        # Dad keeps his account (he has Brian too); his chat with the teacher is about Amina.
        chat = Conversation.objects.create(school=self.school_a, kind=Conversation.Kind.DIRECT, student=self.kid,
                                           created_by=self.user_a)
        ConversationParticipant.objects.create(conversation=chat, user=self.user_a)
        ConversationParticipant.objects.create(conversation=chat, user=self.dad.user)
        Message.objects.create(conversation=chat, sender=self.dad.user, body="Is Amina's homework in?")
        self.dad_chat = chat
        ParentSignupRequest.objects.create(school=self.school_a, school_class=self.klass, name="Aunt",
                                           email="aunt@example.org", admission_number="ADM1", student=self.kid)

    def json_export(self, student=None):
        response = self.admin.get(f"/api/students/{(student or self.kid).id}/data-export/", {"format": "json"})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_export_includes_subject_comments_and_conversations_about_the_child(self):
        data = self.json_export()
        self.assertEqual(data["student"]["first_name"], "Amina")
        self.assertIn("Amina reads widely; Amina Otieno should keep it up.",
                      [row["comment"] for row in data["subject_comments"]])
        about = [m["message"] for m in data["conversations_about_the_student"]]
        self.assertIn("Is Amina's homework in?", about)
        self.assertIn("Amina has a cough today", about)
        for key in ("parents", "grades", "attendance", "reports", "parent_messages"):
            self.assertIn(key, data)

    def test_json_export_is_logged_and_admin_only(self):
        from activity.models import ActivityLog

        self.json_export()
        self.assertTrue(ActivityLog.objects.filter(action="student.data_exported").exists())
        self.assertEqual(self.client_a.get(f"/api/students/{self.kid.id}/data-export/", {"format": "json"})
                         .status_code, 403)
        self.assertEqual(self.client_b.get(f"/api/students/{self.kid.id}/data-export/", {"format": "json"})
                         .status_code, 403)

    def test_after_removal_nothing_identifies_the_child(self):
        self.assertEqual(self.remove().status_code, 200)
        dump = json.dumps(self.json_export())
        for secret in ("Amina", "ADM1", "Asthma", "Hospital appointment", "2013-05-01"):
            self.assertNotIn(secret, dump)
        comment = SubjectReport.objects.get(student=self.kid).comment
        self.assertNotIn("Amina", comment)
        self.assertNotIn("Otieno", comment)
        self.assertIn("Removed student", comment)
        dad_message = Message.objects.get(conversation=self.dad_chat).body
        self.assertEqual(dad_message, "Is Removed student's homework in?")
        self.assertFalse(ParentSignupRequest.objects.filter(student=self.kid).exists())

    def test_removal_leaves_other_childrens_text_alone(self):
        self.remove()
        self.assertEqual(SubjectReport.objects.get(student=self.other).comment, "Cy writes clearly.")


class RetentionTests(FamilyDataFixture):
    def run_retention(self, *args):
        out = StringIO()
        call_command("apply_retention", *args, stdout=out)
        return out.getvalue()

    def leave(self, student, years_ago):
        student.is_active = False
        student.graduated_on = timezone.localdate() - timedelta(days=round(365.25 * years_ago))
        student.save()

    def test_off_by_default(self):
        self.leave(self.kid, 10)
        output = self.run_retention("--apply")
        self.assertIn("off", output)
        self.assertEqual(Student.objects.get(pk=self.kid.pk).first_name, "Amina")

    @override_settings(RETENTION_INACTIVE_STUDENT_YEARS=3)
    def test_dry_run_by_default_then_apply(self):
        self.leave(self.kid, 4)
        self.leave(self.other, 1)  # left recently: kept
        output = self.run_retention()
        self.assertIn("Would anonymise 1 student", output)
        self.assertEqual(Student.objects.get(pk=self.kid.pk).first_name, "Amina")

        output = self.run_retention("--apply")
        self.assertIn("Anonymised 1 student", output)
        self.assertEqual(Student.objects.get(pk=self.kid.pk).first_name, "Removed")
        self.assertEqual(Student.objects.get(pk=self.other.pk).first_name, "Cy")
        self.assertEqual(Student.objects.get(pk=self.sibling.pk).first_name, "Brian")  # still active

    @override_settings(RETENTION_INACTIVE_STUDENT_YEARS=3)
    def test_inactive_students_without_a_leaving_date_are_reported_not_touched(self):
        self.kid.is_active = False
        self.kid.save()
        output = self.run_retention("--apply")
        self.assertIn("1 inactive student(s) have no leaving date", output)
        self.assertEqual(Student.objects.get(pk=self.kid.pk).first_name, "Amina")

    @override_settings(RETENTION_INACTIVE_STUDENT_YEARS=3)
    def test_already_anonymised_students_are_skipped(self):
        self.leave(self.kid, 4)
        self.run_retention("--apply")
        output = self.run_retention("--apply")
        self.assertIn("Anonymised 0 student", output)
