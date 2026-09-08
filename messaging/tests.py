"""
Tests for the direct-messaging feature: creating conversations, sending
messages, read tracking, contacts, and cross-school/permission isolation.
"""
from accounts.tests import SchoolScopedAPITestCase
from guardians.models import Guardian
from students.models import Student


class MessagingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.student = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno"
        )
        self.guardian_user = self.user_a.__class__.objects.create_user(
            username="grace_g", email="grace@example.com", password="pass1234"
        )
        self.guardian = Guardian.objects.create(
            user=self.guardian_user, school=self.school_a, display_name="Grace Otieno"
        )
        self.guardian.students.add(self.student)
        self.guardian_client = self.authed_client(self.guardian_user)

    def test_teacher_can_start_conversation_with_guardian(self):
        response = self.client_a.post(
            "/api/conversations/",
            {
                "participant_ids": [self.guardian_user.id],
                "student": self.student.id,
                "body": "Hi Grace, Amina did great in math today.",
            },
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["student_name"], "Amina Otieno")
        self.assertEqual(len(response.data["participants"]), 2)

    def test_guardian_sees_the_conversation_and_can_reply(self):
        create = self.client_a.post(
            "/api/conversations/",
            {"participant_ids": [self.guardian_user.id], "body": "Hi Grace."},
        )
        conv_id = create.data["id"]

        listing = self.guardian_client.get("/api/conversations/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data), 1)

        reply = self.guardian_client.post(
            f"/api/conversations/{conv_id}/messages/", {"body": "Thank you for letting me know!"}
        )
        self.assertEqual(reply.status_code, 201, reply.data)
        self.assertEqual(reply.data["sender_kind"], "guardian")

        thread = self.client_a.get(f"/api/conversations/{conv_id}/messages/")
        self.assertEqual(thread.status_code, 200)
        self.assertEqual(len(thread.data), 2)

    def test_non_participant_staff_cannot_see_or_message_the_conversation(self):
        create = self.client_a.post(
            "/api/conversations/",
            {"participant_ids": [self.guardian_user.id], "body": "Private note."},
        )
        conv_id = create.data["id"]

        other_teacher = self.user_a.__class__.objects.create_user(
            username="other_teacher", email="other@alpha.test", password="pass1234"
        )
        from accounts.models import Profile
        Profile.objects.create(user=other_teacher, school=self.school_a, role=Profile.Role.TEACHER)
        other_client = self.authed_client(other_teacher)

        get_resp = other_client.get(f"/api/conversations/{conv_id}/messages/")
        self.assertEqual(get_resp.status_code, 404)

        # Also shouldn't show up in their list.
        listing = other_client.get("/api/conversations/")
        self.assertEqual(len(listing.data), 0)

    def test_cannot_add_a_participant_from_another_school(self):
        outside_guardian_user = self.user_b.__class__.objects.create_user(
            username="paul_g", email="paul@example.com", password="pass1234"
        )
        Guardian.objects.create(user=outside_guardian_user, school=self.school_b, display_name="Paul Kiptoo")

        response = self.client_a.post(
            "/api/conversations/",
            {"participant_ids": [outside_guardian_user.id], "body": "Hello?"},
        )
        self.assertEqual(response.status_code, 400)

    def test_read_tracking_marks_unread_zero_after_read(self):
        create = self.client_a.post(
            "/api/conversations/",
            {"participant_ids": [self.guardian_user.id], "body": "First message."},
        )
        conv_id = create.data["id"]

        # Guardian hasn't read it yet.
        listing_before = self.guardian_client.get("/api/conversations/")
        self.assertEqual(listing_before.data[0]["unread_count"], 1)

        self.guardian_client.post(f"/api/conversations/{conv_id}/read/")

        listing_after = self.guardian_client.get("/api/conversations/")
        self.assertEqual(listing_after.data[0]["unread_count"], 0)

    def test_contacts_endpoint_returns_the_other_identity_type(self):
        staff_contacts = self.client_a.get("/api/conversations/contacts/")
        self.assertEqual(staff_contacts.status_code, 200)
        kinds = {row["kind"] for row in staff_contacts.data}
        self.assertEqual(kinds, {"guardian"})

        guardian_contacts = self.guardian_client.get("/api/conversations/contacts/")
        self.assertEqual(guardian_contacts.status_code, 200)
        kinds = {row["kind"] for row in guardian_contacts.data}
        self.assertEqual(kinds, {"staff"})

    def test_unauthenticated_request_is_401(self):
        from rest_framework.test import APIClient

        response = APIClient().get("/api/conversations/")
        self.assertEqual(response.status_code, 401)

    def test_empty_message_body_rejected(self):
        response = self.client_a.post(
            "/api/conversations/",
            {"participant_ids": [self.guardian_user.id], "body": "   "},
        )
        self.assertEqual(response.status_code, 400)
