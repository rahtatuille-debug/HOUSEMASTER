"""
A school still being set up is open to its admins only, on the server and not just in the app: other staff can see
their account (and are told to wait), parents and students can only sign out.
"""
from django.contrib.auth.models import User
from django.utils import timezone

from guardians.models import Guardian
from students.models import Student
from studentaccounts import services as student_accounts

from .tests import SchoolScopedAPITestCase


class SetupGateTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.school_a.setup_completed_at = None
        self.school_a.save(update_fields=["setup_completed_at"])
        self.amina = Student.objects.create(school=self.school_a, first_name="Amina", last_name="K")
        parent = User.objects.create_user(username="pat", email="pat@p.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)
        self.parent = self.authed_client(parent)
        account, _ = student_accounts.create(self.amina, "Admin")
        account.must_change_password = False
        account.save(update_fields=["must_change_password"])
        self.student = self.authed_client(account.user)
        self.admin = self.authed_client(self.admin_a)

    def code(self, response):
        return response.data.get("code") if isinstance(response.data, dict) else None

    def test_admins_can_do_everything(self):
        self.assertEqual(self.admin.get("/api/students/").status_code, 200)
        self.assertEqual(self.admin.get("/api/me/").status_code, 200)

    def test_other_staff_see_their_account_only(self):
        me = self.client_a.get("/api/me/")
        self.assertEqual(me.status_code, 200)
        self.assertFalse(me.data["school"]["setup_completed"])
        response = self.client_a.get("/api/students/")
        self.assertEqual((response.status_code, self.code(response)), (403, "school_not_open"))

    def test_parents_and_students_wait(self):
        for client, path in ((self.parent, "/api/guardian-me/"), (self.parent, "/api/guardian-students/"),
                             (self.student, "/api/student/me/")):
            response = client.get(path)
            self.assertEqual((response.status_code, self.code(response)), (403, "school_not_open"), path)

    def test_everyone_gets_in_once_the_school_opens(self):
        self.school_a.setup_completed_at = timezone.now()
        self.school_a.save(update_fields=["setup_completed_at"])
        self.assertEqual(self.client_a.get("/api/students/").status_code, 200)
        self.assertEqual(self.parent.get("/api/guardian-me/").status_code, 200)
        self.assertEqual(self.student.get("/api/student/me/").status_code, 200)

    def test_other_schools_are_unaffected(self):
        self.assertEqual(self.client_b.get("/api/students/").status_code, 200)
