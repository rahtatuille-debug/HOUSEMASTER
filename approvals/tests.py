"""
Tests for teacher changes that need an admin's approval: deleting a
student, changing setup (year groups, classes, subjects, terms), and
changing school settings.
"""
from activity.models import ActivityLog
from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Grade, Subject, Term
from students.models import SchoolClass, Student, YearGroup

from .models import ChangeRequest


class ApprovalFlowTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        self.year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.school_class = SchoolClass.objects.create(year_group=self.year, name="7A")
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.student = Student.objects.create(school=self.school_a, first_name="Ann", last_name="One",
                                              school_class=self.school_class)
        self.assign(self.user_a, self.school_class, self.maths)

    def approve(self, change_request_id, client=None):
        return (client or self.admin_client_a).post(f"/api/change-requests/{change_request_id}/approve/")

    # --- teachers' changes wait for approval

    def test_teacher_creating_a_subject_waits_for_approval(self):
        response = self.client_a.post("/api/subjects/", {"name": "Chemistry"})
        self.assertEqual(response.status_code, 202)
        self.assertFalse(Subject.objects.filter(name="Chemistry").exists())
        change_request = ChangeRequest.objects.get(id=response.data["change_request"]["id"])
        self.assertEqual(change_request.status, "pending")
        self.assertEqual(change_request.summary, 'Add subject "Chemistry"')

        self.assertEqual(self.approve(change_request.id).status_code, 200)
        subject = Subject.objects.get(name="Chemistry")
        self.assertEqual(subject.school, self.school_a)
        change_request.refresh_from_db()
        self.assertEqual(change_request.status, "approved")
        self.assertTrue(ActivityLog.objects.filter(action="subject.created", target_id=subject.id).exists())

    def test_teacher_renaming_a_term_waits_for_approval(self):
        response = self.client_a.patch(f"/api/terms/{self.term.id}/", {"name": "Autumn term"})
        self.assertEqual(response.status_code, 202)
        self.term.refresh_from_db()
        self.assertEqual(self.term.name, "Term 1")
        self.assertIn("from Term 1 to Autumn term", response.data["change_request"]["summary"])
        self.approve(response.data["change_request"]["id"])
        self.term.refresh_from_db()
        self.assertEqual(self.term.name, "Autumn term")

    def test_teacher_changing_report_tone_waits_for_approval(self):
        response = self.client_a.patch(f"/api/schools/{self.school_a.id}/", {"report_tone": "warm"})
        self.assertEqual(response.status_code, 202)
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.report_tone, "formal")
        self.approve(response.data["change_request"]["id"])
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.report_tone, "warm")

    def test_teacher_deleting_a_class_waits_for_approval(self):
        response = self.client_a.delete(f"/api/school-classes/{self.school_class.id}/")
        self.assertEqual(response.status_code, 202)
        self.assertTrue(SchoolClass.objects.filter(id=self.school_class.id).exists())
        self.approve(response.data["change_request"]["id"])
        self.assertFalse(SchoolClass.objects.filter(id=self.school_class.id).exists())

    def test_teacher_deleting_a_student_waits_for_approval(self):
        Grade.objects.create(student=self.student, subject=self.maths, term=self.term, score=50)
        response = self.client_a.delete(f"/api/students/{self.student.id}/", {"reason": "Left the school"})
        self.assertEqual(response.status_code, 202)
        self.assertTrue(Student.objects.filter(id=self.student.id).exists())
        self.assertEqual(response.data["change_request"]["reason"], "Left the school")
        self.approve(response.data["change_request"]["id"])
        self.assertFalse(Student.objects.filter(id=self.student.id).exists())
        self.assertFalse(Grade.objects.filter(student_id=self.student.id).exists())
        self.assertTrue(ActivityLog.objects.filter(action="student.deleted").exists())

    def test_teacher_cannot_request_deleting_a_student_outside_their_classes(self):
        other = Student.objects.create(school=self.school_a, first_name="Not", last_name="Mine")
        response = self.client_a.delete(f"/api/students/{other.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ChangeRequest.objects.exists())

    def test_teacher_can_still_add_and_deactivate_students_directly(self):
        response = self.client_a.post("/api/students/", {"first_name": "New", "last_name": "Kid",
                                                         "school_class": self.school_class.id})
        self.assertEqual(response.status_code, 201)
        response = self.client_a.patch(f"/api/students/{self.student.id}/", {"is_active": False})
        self.assertEqual(response.status_code, 200)

    def test_invalid_teacher_change_is_rejected_straight_away(self):
        response = self.client_a.post("/api/subjects/", {"name": ""})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ChangeRequest.objects.exists())

    def test_teacher_cannot_request_a_class_in_another_schools_year_group(self):
        other_year = YearGroup.objects.create(school=self.school_b, name="Year 9")
        response = self.client_a.post("/api/school-classes/", {"year_group": other_year.id, "name": "9Z"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ChangeRequest.objects.exists())

    def test_request_with_no_change_is_rejected(self):
        response = self.client_a.patch(f"/api/terms/{self.term.id}/", {"name": "Term 1"})
        self.assertEqual(response.status_code, 400)

    # --- admins act directly

    def test_admin_changes_apply_immediately_and_are_logged(self):
        response = self.admin_client_a.post("/api/subjects/", {"name": "Biology"})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Subject.objects.filter(name="Biology").exists())
        response = self.admin_client_a.delete(f"/api/students/{self.student.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertTrue(ActivityLog.objects.filter(action="subject.created").exists())
        self.assertTrue(ActivityLog.objects.filter(action="student.deleted").exists())
        self.assertFalse(ChangeRequest.objects.exists())

    # --- reviewing

    def test_admin_rejects_with_a_note(self):
        response = self.client_a.post("/api/subjects/", {"name": "Chemistry"})
        cr_id = response.data["change_request"]["id"]
        response = self.admin_client_a.post(f"/api/change-requests/{cr_id}/reject/", {"note": "We have one"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "rejected")
        self.assertEqual(response.data["review_note"], "We have one")
        self.assertFalse(Subject.objects.filter(name="Chemistry").exists())
        # A decided request can't be approved afterwards.
        self.assertEqual(self.approve(cr_id).status_code, 400)

    def test_teacher_cannot_approve_or_reject(self):
        cr_id = self.client_a.post("/api/subjects/", {"name": "Chemistry"}).data["change_request"]["id"]
        self.assertEqual(self.approve(cr_id, client=self.client_a).status_code, 403)
        self.assertEqual(self.client_a.post(f"/api/change-requests/{cr_id}/reject/").status_code, 403)

    def test_teacher_sees_only_own_requests_and_admin_sees_all(self):
        other_teacher = self._second_teacher()
        self.client_a.post("/api/subjects/", {"name": "Chemistry"})
        self.authed_client(other_teacher).post("/api/subjects/", {"name": "Physics"})
        mine = [r["summary"] for r in self.client_a.get("/api/change-requests/").data]
        self.assertEqual(mine, ['Add subject "Chemistry"'])
        self.assertEqual(len(self.admin_client_a.get("/api/change-requests/").data), 2)

    def test_other_school_cannot_see_or_approve_requests(self):
        cr_id = self.client_a.post("/api/subjects/", {"name": "Chemistry"}).data["change_request"]["id"]
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get("/api/change-requests/").data, [])
        self.assertEqual(self.approve(cr_id, client=self.client_b).status_code, 404)

    def test_teacher_cancels_own_pending_request(self):
        cr_id = self.client_a.post("/api/subjects/", {"name": "Chemistry"}).data["change_request"]["id"]
        response = self.client_a.post(f"/api/change-requests/{cr_id}/cancel/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(self.approve(cr_id).status_code, 400)

    def test_approving_after_the_item_was_deleted_fails_cleanly(self):
        cr_id = self.client_a.patch(f"/api/terms/{self.term.id}/", {"name": "New"}).data["change_request"]["id"]
        self.term.delete()
        response = self.approve(cr_id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ChangeRequest.objects.get(id=cr_id).status, "pending")

    def _second_teacher(self):
        from django.contrib.auth.models import User

        from accounts.models import Profile

        user = User.objects.create_user(username="t2@alpha.test", email="t2@alpha.test", password="pass1234")
        Profile.objects.create(user=user, school=self.school_a, role=Profile.Role.TEACHER)
        return user
