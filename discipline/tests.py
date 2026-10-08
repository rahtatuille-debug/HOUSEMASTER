"""
Discipline records (owner's request, 2026-10-08): staff record a student's
behaviour incidents and what was done; parents see a record only once it is
shared with them, and never the staff notes.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from gradebook.models import Subject
from guardians.models import Guardian
from students.localtime import school_localdate
from students.models import SchoolClass, Student, YearGroup

from .models import DisciplineIncident

URL = "/api/discipline/incidents/"
SECRET = "Private staff note about the fight"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class Fixture(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        self.teacher = self.client_a
        year = YearGroup.objects.create(school=self.school_a, name="Form 2")
        self.mine = SchoolClass.objects.create(year_group=year, name="2 East")
        self.theirs = SchoolClass.objects.create(year_group=year, name="2 West")
        self.assign(self.user_a, self.mine, Subject.objects.create(school=self.school_a, name="Maths"))
        self.amina = Student.objects.create(school=self.school_a, first_name="Amina", last_name="K",
                                            school_class=self.mine)
        self.ben = Student.objects.create(school=self.school_a, first_name="Ben", last_name="K",
                                          school_class=self.theirs)
        parent = User.objects.create_user(username="pa@alpha.test", email="pa@alpha.test", password="x")
        self.guardian = Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat")
        self.guardian.students.add(self.amina)
        self.parent = self.authed_client(parent)

    def record(self, client=None, student=None, **extra):
        body = {"student": (student or self.amina).id, "category": "fighting", "severity": "serious",
                "description": "Pushed another pupil at break.", "action": "detention",
                "action_detail": "Detention Friday 3pm", "staff_notes": SECRET, **extra}
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.teacher).post(URL, body, format="json")

    def patch(self, incident_id, body, client=None):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.teacher).patch(f"{URL}{incident_id}/", body, format="json")


class DisciplineTests(Fixture):

    def test_a_teacher_records_an_incident_for_their_pupil(self):
        response = self.record()
        self.assertEqual(response.status_code, 201, response.data)
        incident = DisciplineIncident.objects.get()
        self.assertEqual((incident.student, incident.school, incident.date),
                         (self.amina, self.school_a, school_localdate(self.school_a)))
        self.assertEqual(response.data["category_label"], "Fighting")
        self.assertEqual(response.data["recorded_by_name"], incident.recorded_by_name)
        self.assertFalse(incident.shared_with_parents)
        self.assertEqual(len(mail.outbox), 0)  # not shared: parents aren't told

    def test_the_log_never_holds_the_description_or_notes(self):
        self.record()
        entry = ActivityLog.objects.get(action="discipline.recorded")
        self.assertIn("Amina K", entry.summary)
        self.assertIn("Fighting", entry.summary)
        for text in ("Pushed", SECRET):
            self.assertFalse(ActivityLog.objects.filter(summary__icontains=text).exists())
            self.assertNotIn(text, str(entry.details))

    def test_sharing_emails_parents_and_they_see_it_without_staff_notes(self):
        response = self.record(shared_with_parents=True)
        self.assertEqual(response.data["parents_emailed"], 1)
        self.assertEqual(mail.outbox[0].to, ["pa@alpha.test"])
        self.assertNotIn("Pushed", mail.outbox[0].body)  # the details stay in HouseMaster
        rows = self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/").data["discipline"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Pushed another pupil at break.")
        self.assertEqual(rows[0]["action_detail"], "Detention Friday 3pm")
        self.assertNotIn(SECRET, str(rows))
        self.assertNotIn("staff_notes", rows[0])

    def test_parents_never_see_unshared_records(self):
        self.record()
        rows = self.parent.get(f"/api/guardian-students/{self.amina.id}/profile/").data["discipline"]
        self.assertEqual(rows, [])

    def test_sharing_later_emails_once(self):
        incident_id = self.record().data["id"]
        response = self.patch(incident_id, {"shared_with_parents": True})
        self.assertEqual(response.data["parents_emailed"], 1)
        response = self.patch(incident_id, {"action_detail": "Detention moved"})
        self.assertEqual(response.data["parents_emailed"], 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_teacher_cannot_record_or_see_pupils_outside_their_classes(self):
        self.assertEqual(self.record(student=self.ben).data, {"student": ["Student not found."]})
        DisciplineIncident.objects.create(school=self.school_a, student=self.ben, date=school_localdate(self.school_a),
                                          category="late", description="Late", staff_notes=SECRET)
        self.assertEqual(self.teacher.get(URL).data, [])
        self.assertEqual(len(self.admin.get(URL).data), 1)

    def test_only_the_recorder_or_an_admin_changes_it_and_only_admins_delete(self):
        incident = DisciplineIncident.objects.create(school=self.school_a, student=self.amina, category="late",
                                                     date=school_localdate(self.school_a), description="Late",
                                                     recorded_by=self.admin_a)
        self.assertEqual(self.teacher.patch(f"{URL}{incident.id}/", {"severity": "serious"},
                                            format="json").status_code, 403)
        rows = {r["id"]: r["can_edit"] for r in self.teacher.get(URL).data}
        self.assertFalse(rows[incident.id])
        self.assertTrue(all(r["can_edit"] for r in self.admin.get(URL).data))
        mine = self.record().data["id"]
        self.assertTrue(self.teacher.get(f"{URL}{mine}/").data["can_edit"])
        self.assertEqual(self.teacher.patch(f"{URL}{mine}/", {"severity": "moderate"}, format="json").status_code, 200)
        self.assertEqual(self.teacher.delete(f"{URL}{mine}/").status_code, 403)
        self.assertEqual(self.admin.delete(f"{URL}{mine}/").status_code, 204)
        self.assertTrue(ActivityLog.objects.filter(action="discipline.deleted", target_id=self.amina.id).exists())

    def test_the_student_cannot_be_swapped_by_an_edit(self):
        mine = self.record().data["id"]
        self.teacher.patch(f"{URL}{mine}/", {"student": self.ben.id}, format="json")
        self.assertEqual(DisciplineIncident.objects.get(pk=mine).student, self.amina)

    def test_future_dates_and_empty_descriptions_are_refused(self):
        tomorrow = (school_localdate(self.school_a) + timedelta(days=1)).isoformat()
        self.assertEqual(self.record(date=tomorrow).status_code, 400)
        self.assertEqual(self.record(description="  ").status_code, 400)
        self.assertEqual(self.record(category="nonsense").status_code, 400)

    def test_filters(self):
        self.record()
        self.record(category="late", severity="minor", date=(school_localdate(self.school_a) - timedelta(days=9)).isoformat())
        self.assertEqual(len(self.teacher.get(URL, {"category": "late"}).data), 1)
        self.assertEqual(len(self.teacher.get(URL, {"severity": "serious"}).data), 1)
        since = (school_localdate(self.school_a) - timedelta(days=2)).isoformat()
        self.assertEqual(len(self.teacher.get(URL, {"from": since}).data), 1)
        self.assertEqual(len(self.teacher.get(URL, {"student": self.amina.id}).data), 2)
        self.assertEqual(self.teacher.get(URL, {"from": "soon"}).status_code, 400)

    def test_choices_and_the_staff_profile(self):
        choices = self.teacher.get(f"{URL}choices/").data
        self.assertIn(["fighting", "Fighting"], [list(c) for c in choices["categories"]])
        self.record()
        profile = self.teacher.get(f"/api/students/{self.amina.id}/profile/").data["discipline"]
        self.assertEqual(profile["count"], 1)
        self.assertEqual(profile["recent"][0]["staff_notes"], SECRET)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class DisciplineIsolationTests(Fixture):
    """Another school, a parent of another child and the public reach nothing."""

    def setUp(self):
        super().setUp()
        self.incident = DisciplineIncident.objects.create(
            school=self.school_a, student=self.ben, date=school_localdate(self.school_a), category="bullying",
            description="Name-calling", staff_notes=SECRET, shared_with_parents=True)
        self.make_admin(self.user_b)

    def test_another_schools_admin_reaches_nothing(self):
        self.assertEqual(self.client_b.get(URL).data, [])
        self.assertEqual(self.client_b.get(f"{URL}{self.incident.id}/").status_code, 404)
        self.assertEqual(self.client_b.patch(f"{URL}{self.incident.id}/", {"severity": "minor"},
                                             format="json").status_code, 404)
        self.assertEqual(self.client_b.delete(f"{URL}{self.incident.id}/").status_code, 404)
        self.assertEqual(self.record(client=self.client_b, student=self.ben).data, {"student": ["Student not found."]})

    def test_a_parent_of_another_child_sees_nothing(self):
        self.assertEqual(self.parent.get(f"/api/guardian-students/{self.ben.id}/profile/").status_code, 404)
        self.assertEqual(self.parent.get(URL).status_code, 403)

    def test_the_public_sees_nothing(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
        self.assertEqual(APIClient().get(f"{URL}{self.incident.id}/").status_code, 401)


class DisciplinePrivacyTests(Fixture):
    def test_export_includes_and_erasure_removes_records(self):
        self.record(shared_with_parents=False)
        from students.privacy import family_export_data, remove_personal_data

        from students.privacy import family_export

        self.assertTrue(family_export(self.amina))  # the spreadsheet builds with the new sheet
        exported = family_export_data(self.amina)
        self.assertEqual(exported["discipline"][0]["staff_notes"], SECRET)
        counts = remove_personal_data(self.amina, self.admin_a)
        self.assertEqual(counts["discipline_records_deleted"], 1)
        self.assertFalse(DisciplineIncident.objects.filter(student=self.amina).exists())
