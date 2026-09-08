"""
Tests for the guardian-account flow: invite -> accept -> guardian_me,
plus scoping and permission boundaries relative to staff.
"""
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from students.models import Student


class GuardianInviteFlowTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        self.student = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno"
        )

    def test_non_admin_cannot_create_guardian_invite(self):
        response = self.client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace@example.com", "students": [self.student.id]},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_guardian_invite(self):
        response = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace@example.com", "students": [self.student.id]},
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_cannot_invite_guardian_to_another_schools_student(self):
        other_student = Student.objects.create(
            school=self.school_b, first_name="Brian", last_name="Kiptoo"
        )
        response = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Paul Kiptoo", "email": "paul@example.com", "students": [other_student.id]},
        )
        self.assertEqual(response.status_code, 403)

    def test_requires_at_least_one_student(self):
        response = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace@example.com", "students": []},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("students", response.data)

    def test_full_accept_flow_creates_guardian_linked_to_students(self):
        create = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace@example.com", "students": [self.student.id]},
        )
        token = create.data["token"]

        preview = APIClient().get(f"/api/guardian-invites/preview/{token}/")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["school_name"], "Alpha Academy")
        self.assertEqual(preview.data["student_names"], ["Amina Otieno"])

        accept = APIClient().post(
            "/api/guardian-invites/accept/", {"token": token, "password": "SuperSecret123!"}
        )
        self.assertEqual(accept.status_code, 201, accept.data)
        self.assertIn("access", accept.data)

        guardian_client = APIClient()
        guardian_client.credentials(HTTP_AUTHORIZATION=f"Bearer {accept.data['access']}")
        me = guardian_client.get("/api/guardian-me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["name"], "Grace Otieno")
        self.assertEqual(me.data["school"]["name"], "Alpha Academy")
        self.assertEqual(len(me.data["students"]), 1)
        self.assertEqual(me.data["students"][0]["first_name"], "Amina")

    def test_guardian_cannot_use_staff_endpoints(self):
        create = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace2@example.com", "students": [self.student.id]},
        )
        accept = APIClient().post(
            "/api/guardian-invites/accept/",
            {"token": create.data["token"], "password": "SuperSecret123!"},
        )
        guardian_client = APIClient()
        guardian_client.credentials(HTTP_AUTHORIZATION=f"Bearer {accept.data['access']}")

        # A guardian has no Profile, so the broad staff surface must reject them.
        response = guardian_client.get("/api/students/")
        self.assertEqual(response.status_code, 403)

    def test_guardian_can_update_own_display_name(self):
        create = self.admin_client_a.post(
            "/api/guardian-invites/",
            {"name": "Grace Otieno", "email": "grace3@example.com", "students": [self.student.id]},
        )
        accept = APIClient().post(
            "/api/guardian-invites/accept/",
            {"token": create.data["token"], "password": "SuperSecret123!"},
        )
        guardian_client = APIClient()
        guardian_client.credentials(HTTP_AUTHORIZATION=f"Bearer {accept.data['access']}")

        response = guardian_client.patch("/api/guardian-me/", {"name": "Grace M. Otieno"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Grace M. Otieno")
