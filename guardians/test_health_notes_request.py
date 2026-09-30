"""
Parents suggesting a change to their child's health notes. The suggestion
is a pending change request: nothing changes until a school admin approves
it (the school keeps its records), and the note text stays out of the
activity log.
"""
from django.contrib.auth.models import User

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from approvals.models import ChangeRequest
from students.models import SchoolClass, Student, YearGroup

from .models import Guardian

NEW_NOTES = "Peanut allergy: EpiPen in the front pocket of the school bag."


class HealthNotesRequestTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        year = YearGroup.objects.create(school=self.school_a, name="Class 8")
        klass = SchoolClass.objects.create(year_group=year, name="8A")
        self.child = Student.objects.create(school=self.school_a, first_name="Jaden", last_name="Afrika",
                                            school_class=klass, medical_notes="Asthma")
        self.other_child = Student.objects.create(school=self.school_a, first_name="Brian", last_name="Kamau",
                                                  school_class=klass)
        self.parent_user = User.objects.create_user(username="pa@alpha.test", email="pa@alpha.test", password="x")
        Guardian.objects.create(user=self.parent_user, school=self.school_a, display_name="Pat Afrika") \
            .students.add(self.child)
        self.parent = self.authed_client(self.parent_user)
        other_user = User.objects.create_user(username="pk@alpha.test", email="pk@alpha.test", password="x")
        Guardian.objects.create(user=other_user, school=self.school_a, display_name="Kim Kamau") \
            .students.add(self.other_child)
        self.other_parent = self.authed_client(other_user)
        self.admin = self.authed_client(self.admin_a)
        admin_b = User.objects.create_user(username="ab@beta.test", email="ab@beta.test", password="x")
        Profile.objects.create(user=admin_b, school=self.school_b, role=Profile.Role.ADMIN)
        self.admin_b = self.authed_client(admin_b)

    def url(self, student=None):
        return f"/api/guardian-students/{(student or self.child).id}/health-notes-request/"

    def suggest(self, notes=NEW_NOTES, client=None, **extra):
        return (client or self.parent).post(self.url(), {"medical_notes": notes, **extra}, format="json")

    def pending(self):
        return ChangeRequest.objects.get(status=ChangeRequest.Status.PENDING)

    # --- suggesting ---

    def test_parent_suggestion_waits_for_the_school(self):
        response = self.suggest(reason="Diagnosed last month")
        self.assertEqual(response.status_code, 201, response.data)
        request = self.pending()
        self.assertEqual(request.school, self.school_a)
        self.assertEqual((request.kind, request.operation, request.target_id), ("student", "update", self.child.id))
        self.assertEqual(request.data, {"medical_notes": NEW_NOTES})
        self.assertEqual(request.reason, "Diagnosed last month")
        self.assertEqual(request.requested_by, self.parent_user)
        self.child.refresh_from_db()
        self.assertEqual(self.child.medical_notes, "Asthma")

    def test_admin_sees_the_suggestion_with_the_new_text(self):
        self.suggest()
        rows = self.admin.get("/api/change-requests/", {"status": "pending"}).data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["data"], {"medical_notes": NEW_NOTES})
        self.assertIn("Jaden Afrika", rows[0]["summary"])
        self.assertIn("parent", rows[0]["summary"].lower())
        self.assertNotIn(NEW_NOTES, rows[0]["summary"])

    def test_approving_updates_the_health_notes(self):
        self.suggest()
        response = self.admin.post(f"/api/change-requests/{self.pending().id}/approve/")
        self.assertEqual(response.status_code, 200, response.data)
        self.child.refresh_from_db()
        self.assertEqual(self.child.medical_notes, NEW_NOTES)

    def test_rejecting_leaves_them_and_the_parent_sees_why(self):
        self.suggest()
        request_id = self.pending().id
        self.admin.post(f"/api/change-requests/{request_id}/reject/", {"note": "Please bring the doctor's letter."})
        self.child.refresh_from_db()
        self.assertEqual(self.child.medical_notes, "Asthma")
        shown = self.parent.get(f"/api/guardian-students/{self.child.id}/profile/").data["health_notes_request"]
        self.assertEqual(shown["status"], "rejected")
        self.assertEqual(shown["review_note"], "Please bring the doctor's letter.")

    def test_parent_sees_their_waiting_suggestion_on_the_profile(self):
        self.assertIsNone(self.parent.get(f"/api/guardian-students/{self.child.id}/profile/").data["health_notes_request"])
        self.suggest()
        shown = self.parent.get(f"/api/guardian-students/{self.child.id}/profile/").data["health_notes_request"]
        self.assertEqual(shown["status"], "pending")
        self.assertEqual(shown["medical_notes"], NEW_NOTES)

    def test_only_the_health_notes_can_be_changed_this_way(self):
        self.suggest(first_name="Hacked", date_of_birth="2001-01-01", school_class=None)
        self.assertEqual(self.pending().data, {"medical_notes": NEW_NOTES})
        self.admin.post(f"/api/change-requests/{self.pending().id}/approve/")
        self.child.refresh_from_db()
        self.assertEqual(self.child.first_name, "Jaden")
        self.assertIsNotNone(self.child.school_class)

    def test_one_waiting_suggestion_at_a_time_and_it_can_be_withdrawn(self):
        self.suggest()
        self.assertEqual(self.suggest("Something else").status_code, 400)
        self.assertEqual(self.parent.delete(self.url()).status_code, 200)
        self.assertEqual(ChangeRequest.objects.get().status, ChangeRequest.Status.CANCELLED)
        self.assertEqual(self.suggest("Something else").status_code, 201)

    def test_withdrawing_with_nothing_waiting(self):
        self.assertEqual(self.parent.delete(self.url()).status_code, 404)

    def test_nothing_to_change(self):
        self.assertEqual(self.suggest("Asthma").status_code, 400)
        self.assertEqual(self.suggest("  Asthma  ").status_code, 400)

    def test_clearing_the_notes_is_a_valid_suggestion(self):
        self.assertEqual(self.suggest("").status_code, 201)
        self.assertEqual(self.pending().data, {"medical_notes": ""})

    def test_too_long(self):
        self.assertEqual(self.suggest("x" * 2001).status_code, 400)

    def test_not_for_a_child_who_has_left(self):
        Student.objects.filter(id=self.child.id).update(is_active=False)
        self.assertEqual(self.suggest().status_code, 400)

    def test_the_health_text_stays_out_of_the_activity_log(self):
        self.suggest()
        self.admin.post(f"/api/change-requests/{self.pending().id}/approve/")
        self.assertTrue(ActivityLog.objects.exists())
        for entry in ActivityLog.objects.all():
            self.assertNotIn("EpiPen", entry.summary)
            self.assertNotIn("EpiPen", str(entry.details))

    # --- who can ---

    def test_not_for_another_familys_child(self):
        response = self.parent.post(self.url(self.other_child), {"medical_notes": "x"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ChangeRequest.objects.exists())

    def test_another_parent_cannot_withdraw_or_see_it(self):
        self.suggest()
        self.assertEqual(self.other_parent.delete(self.url()).status_code, 404)
        self.assertEqual(self.pending().status, ChangeRequest.Status.PENDING)

    def test_staff_use_their_own_screens_not_this_endpoint(self):
        for client in (self.admin, self.client_a):
            self.assertEqual(client.post(self.url(), {"medical_notes": "x"}, format="json").status_code, 403)

    def test_another_school_cannot_see_or_approve_it(self):
        self.suggest()
        request_id = self.pending().id
        self.assertEqual(self.admin_b.get("/api/change-requests/").data, [])
        self.assertEqual(self.admin_b.post(f"/api/change-requests/{request_id}/approve/").status_code, 404)
        self.child.refresh_from_db()
        self.assertEqual(self.child.medical_notes, "Asthma")

    def test_teachers_do_not_see_parents_suggestions(self):
        self.suggest()
        self.assertEqual(self.client_a.get("/api/change-requests/").data, [])
