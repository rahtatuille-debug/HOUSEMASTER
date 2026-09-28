"""
Tests for the direct-messaging feature: creating conversations, sending
messages, read tracking, contacts, and cross-school/permission isolation.
"""
from accounts.tests import SchoolScopedAPITestCase
from guardians.models import Guardian
from gradebook.models import Subject
from students.models import SchoolClass, Student, YearGroup


class MessagingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.school_class = SchoolClass.objects.create(year_group=year, name="7A")
        self.student = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno", school_class=self.school_class
        )
        # user_a teaches Amina's class, so may message her parent.
        self.assign(self.user_a, self.school_class, Subject.objects.create(school=self.school_a, name="Maths"))
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
        self.assertEqual(len(listing.data["results"]), 1)

        reply = self.guardian_client.post(
            f"/api/conversations/{conv_id}/messages/", {"body": "Thank you for letting me know!"}
        )
        self.assertEqual(reply.status_code, 201, reply.data)
        self.assertEqual(reply.data["sender_kind"], "guardian")

        thread = self.client_a.get(f"/api/conversations/{conv_id}/messages/")
        self.assertEqual(thread.status_code, 200)
        self.assertEqual(thread.data["count"], 2)

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
        self.assertEqual(len(listing.data["results"]), 0)

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
        self.assertEqual(listing_before.data["results"][0]["unread_count"], 1)

        self.guardian_client.post(f"/api/conversations/{conv_id}/read/")

        listing_after = self.guardian_client.get("/api/conversations/")
        self.assertEqual(listing_after.data["results"][0]["unread_count"], 0)

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


class ClassMessageTests(SchoolScopedAPITestCase):
    """A teacher messaging every parent of one class: one-way notices and discussions."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User

        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.class_7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.class_7b = SchoolClass.objects.create(year_group=year, name="7B")
        self.assign(self.user_a, self.class_7a, Subject.objects.create(school=self.school_a, name="Maths"))

        def parent(email, name, school_class):
            student = Student.objects.create(school=self.school_a, first_name=name, last_name="Kid",
                                             school_class=school_class)
            user = User.objects.create_user(username=email, email=email, password="pass1234")
            guardian = Guardian.objects.create(user=user, school=self.school_a, display_name=name + " Parent")
            guardian.students.add(student)
            return user, guardian, student

        self.p1, self.g1, self.kid1 = parent("p1@x.test", "Ann", self.class_7a)
        self.p2, self.g2, self.kid2 = parent("p2@x.test", "Ben", self.class_7a)
        self.p3, self.g3, self.kid3 = parent("p3@x.test", "Cy", self.class_7b)
        self.c1, self.c2, self.c3 = (self.authed_client(u) for u in (self.p1, self.p2, self.p3))

    def send(self, kind, school_class=None, client=None):
        return (client or self.client_a).post("/api/conversations/class/", {
            "school_class": (school_class or self.class_7a).id, "kind": kind, "body": "Trip on Friday",
        })

    def ids(self, client):
        return [c["id"] for c in client.get("/api/conversations/").data["results"]]

    def test_notice_reaches_every_parent_in_the_class_only(self):
        response = self.send("class_notice")
        self.assertEqual(response.status_code, 201)
        conv_id = response.data["id"]
        self.assertIn(conv_id, self.ids(self.c1))
        self.assertIn(conv_id, self.ids(self.c2))
        self.assertNotIn(conv_id, self.ids(self.c3))
        self.assertEqual(self.c1.get(f"/api/conversations/{conv_id}/messages/").data["results"][0]["body"], "Trip on Friday")

    def test_parents_cannot_reply_to_a_notice_or_see_other_recipients(self):
        conv_id = self.send("class_notice").data["id"]
        reply = self.c1.post(f"/api/conversations/{conv_id}/messages/", {"body": "Thanks"})
        self.assertEqual(reply.status_code, 403)
        detail = self.c1.get(f"/api/conversations/{conv_id}/").data
        self.assertFalse(detail["can_reply"])
        names = [p["name"] for p in detail["participants"]]
        self.assertNotIn("Ben Parent", names)
        # The teacher can still add to the notice.
        self.assertEqual(self.client_a.post(f"/api/conversations/{conv_id}/messages/", {"body": "Update"}).status_code, 201)

    def test_discussion_lets_everyone_reply_and_see_each_other(self):
        conv_id = self.send("class_group").data["id"]
        self.assertEqual(self.c1.post(f"/api/conversations/{conv_id}/messages/", {"body": "Can I help?"}).status_code, 201)
        bodies = [m["body"] for m in self.c2.get(f"/api/conversations/{conv_id}/messages/").data["results"]]
        self.assertEqual(bodies, ["Trip on Friday", "Can I help?"])
        names = {p["name"] for p in self.c2.get(f"/api/conversations/{conv_id}/").data["participants"]}
        self.assertTrue({"Ann Parent", "Ben Parent"} <= names)

    def test_teacher_can_only_message_classes_they_teach(self):
        self.assertEqual(self.send("class_notice", school_class=self.class_7b).status_code, 403)
        admin = self.authed_client(self.admin_a)
        self.assertEqual(self.send("class_notice", school_class=self.class_7b, client=admin).status_code, 201)

    def test_parents_cannot_start_class_messages(self):
        self.assertEqual(self.send("class_notice", client=self.c1).status_code, 403)

    def test_parent_who_leaves_the_class_loses_access_at_once(self):
        conv_id = self.send("class_group").data["id"]
        self.kid2.school_class = self.class_7b
        self.kid2.save()
        self.assertNotIn(conv_id, self.ids(self.c2))
        self.assertEqual(self.c2.get(f"/api/conversations/{conv_id}/messages/").status_code, 404)

    def test_parent_who_joins_the_class_is_added_on_the_next_message(self):
        conv_id = self.send("class_group").data["id"]
        self.kid3.school_class = self.class_7a
        self.kid3.save()
        self.client_a.post(f"/api/conversations/{conv_id}/messages/", {"body": "Reminder"})
        self.assertIn(conv_id, self.ids(self.c3))

    def test_deactivated_parents_are_left_out(self):
        self.p2.is_active = False
        self.p2.save()
        conv_id = self.send("class_notice").data["id"]
        from .models import Conversation

        self.assertFalse(Conversation.objects.get(id=conv_id).participant_rows.filter(user=self.p2).exists())

    def test_class_with_no_parent_accounts_is_refused(self):
        empty = SchoolClass.objects.create(year_group=self.class_7a.year_group, name="7C")
        self.assign(self.user_a, empty, Subject.objects.get(name="Maths"))
        self.assertEqual(self.send("class_notice", school_class=empty).status_code, 400)

    def test_cannot_message_another_schools_class(self):
        other_year = YearGroup.objects.create(school=self.school_b, name="Y")
        other_class = SchoolClass.objects.create(year_group=other_year, name="Z")
        admin = self.authed_client(self.admin_a)
        response = self.send("class_notice", school_class=other_class, client=admin)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(str(response.data["school_class"]), "Class not found.")
