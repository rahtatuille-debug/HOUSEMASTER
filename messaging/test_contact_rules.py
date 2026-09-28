"""
F-01: who may start a conversation with whom, and what a refused request
may reveal.

Parents may only message the staff who teach their own children, plus the
school's admins, and may only attach their own children. Staff may only
add parents of children they can see. A refused person or child gets
exactly the same answer as one that doesn't exist, so the endpoint can't be
used to list names.
"""
import json

from django.contrib.auth.models import User

from accounts.tests import SchoolScopedAPITestCase
from gradebook.models import Subject
from guardians.models import Guardian
from students.models import SchoolClass, Student, YearGroup

NOT_FOUND_PARTICIPANT = {"participant_ids": ["One or more participants could not be found."]}
NOT_FOUND_STUDENT = {"student": ["Student not found."]}


class ContactRulesTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.class_7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.class_7b = SchoolClass.objects.create(year_group=year, name="7B")
        maths = Subject.objects.create(school=self.school_a, name="Maths")

        # user_a teaches 7A; teacher_7b teaches 7B only.
        self.assign(self.user_a, self.class_7a, maths)
        self.teacher_7b = self.staff("teacher.7b@alpha.test", "teacher")
        self.assign(self.teacher_7b, self.class_7b, maths)

        self.kid_7a = Student.objects.create(school=self.school_a, first_name="Amina", last_name="Otieno",
                                             school_class=self.class_7a)
        self.kid_7b = Student.objects.create(school=self.school_a, first_name="Brian", last_name="Kamau",
                                             school_class=self.class_7b)

        self.parent_7a = self.parent("grace@example.com", "Grace Otieno", self.kid_7a)
        self.parent_7b = self.parent("peter@example.com", "Peter Kamau", self.kid_7b)
        self.client_parent_7a = self.authed_client(self.parent_7a)
        self.client_admin_a = self.authed_client(self.admin_a)

    def staff(self, email, role):
        from accounts.models import Profile

        user = User.objects.create_user(username=email, email=email, password="pass1234")
        Profile.objects.create(user=user, school=self.school_a, role=role)
        return user

    def parent(self, email, name, *children, school=None):
        user = User.objects.create_user(username=email, email=email, password="pass1234")
        guardian = Guardian.objects.create(user=user, school=school or self.school_a, display_name=name)
        guardian.students.add(*children)
        return user

    def start(self, client, participant_ids, student=None):
        body = {"participant_ids": participant_ids, "body": "Hello"}
        if student is not None:
            body["student"] = student
        return client.post("/api/conversations/", body, format="json")

    # --- parents -------------------------------------------------------

    def test_parent_cannot_message_another_parent(self):
        response = self.start(self.client_parent_7a, [self.parent_7b.id])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

    def test_parent_cannot_message_staff_who_do_not_teach_their_child(self):
        response = self.start(self.client_parent_7a, [self.teacher_7b.id])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

    def test_parent_can_message_their_childs_teacher(self):
        response = self.start(self.client_parent_7a, [self.user_a.id], student=self.kid_7a.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["student_name"], "Amina Otieno")

    def test_parent_can_message_a_school_admin(self):
        response = self.start(self.client_parent_7a, [self.admin_a.id])
        self.assertEqual(response.status_code, 201, response.data)

    def test_parent_cannot_attach_another_familys_child_and_no_name_leaks(self):
        response = self.start(self.client_parent_7a, [self.user_a.id], student=self.kid_7b.id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, NOT_FOUND_STUDENT)
        self.assertNotIn("Brian", str(response.content))
        self.assertNotIn("Kamau", str(response.content))

    def test_parent_walking_ids_learns_nothing(self):
        allowed_users = {self.user_a.id, self.admin_a.id}
        user_ids = [uid for uid in range(1, 51) if uid not in allowed_users and uid != self.parent_7a.id]
        user_answers = {json.dumps(self.start(self.client_parent_7a, [uid]).json()) for uid in user_ids}
        self.assertEqual(user_answers, {json.dumps(NOT_FOUND_PARTICIPANT)})

        student_ids = [sid for sid in range(1, 51) if sid != self.kid_7a.id]
        student_answers = set()
        for sid in student_ids:
            response = self.start(self.client_parent_7a, [self.user_a.id], student=sid)
            self.assertEqual(response.status_code, 400)
            student_answers.add(json.dumps(response.json()))
        self.assertEqual(student_answers, {json.dumps(NOT_FOUND_STUDENT)})

    def test_parent_contacts_list_only_their_childs_teachers_and_admins(self):
        response = self.client_parent_7a.get("/api/conversations/contacts/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["id"] for row in response.data}, {self.user_a.id, self.admin_a.id})

    def test_two_parents_of_the_same_child_both_reach_the_teacher_but_not_each_other(self):
        second_parent = self.parent("otieno2@example.com", "James Otieno", self.kid_7a)
        client = self.authed_client(second_parent)
        self.assertEqual(self.start(client, [self.user_a.id], student=self.kid_7a.id).status_code, 201)
        response = self.start(client, [self.parent_7a.id])
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

    def test_parent_with_children_in_two_classes_reaches_both_teachers(self):
        both = self.parent("both@example.com", "Mary Wanjiru", self.kid_7a, self.kid_7b)
        client = self.authed_client(both)
        self.assertEqual(self.start(client, [self.user_a.id], student=self.kid_7a.id).status_code, 201)
        self.assertEqual(self.start(client, [self.teacher_7b.id], student=self.kid_7b.id).status_code, 201)
        contacts = {row["id"] for row in client.get("/api/conversations/contacts/").data}
        self.assertEqual(contacts, {self.user_a.id, self.teacher_7b.id, self.admin_a.id})

    def test_parent_cannot_reach_deactivated_teacher(self):
        self.user_a.is_active = False
        self.user_a.save(update_fields=["is_active"])
        response = self.start(self.client_parent_7a, [self.user_a.id])
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

    def test_parent_cannot_reach_another_schools_staff(self):
        response = self.start(self.client_parent_7a, [self.user_b.id])
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

    # --- staff ---------------------------------------------------------

    def test_teacher_cannot_add_parent_of_a_child_they_do_not_teach(self):
        response = self.start(self.client_a, [self.parent_7b.id])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

    def test_teacher_cannot_attach_a_child_they_do_not_teach(self):
        response = self.start(self.client_a, [self.parent_7a.id], student=self.kid_7b.id)
        self.assertEqual(response.data, NOT_FOUND_STUDENT)
        self.assertNotIn("Brian", str(response.content))

    def test_teacher_can_message_parent_of_their_pupil(self):
        response = self.start(self.client_a, [self.parent_7a.id], student=self.kid_7a.id)
        self.assertEqual(response.status_code, 201, response.data)

    def test_admin_can_message_any_parent_at_their_school(self):
        response = self.start(self.client_admin_a, [self.parent_7b.id], student=self.kid_7b.id)
        self.assertEqual(response.status_code, 201, response.data)

    def test_staff_cannot_reach_another_schools_parent(self):
        other_year = YearGroup.objects.create(school=self.school_b, name="Y")
        other_kid = Student.objects.create(school=self.school_b, first_name="Zed", last_name="Other",
                                           school_class=SchoolClass.objects.create(year_group=other_year, name="Z"))
        other_parent = self.parent("zed@example.com", "Zed Parent", other_kid, school=self.school_b)
        response = self.start(self.client_admin_a, [other_parent.id])
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)
        response = self.start(self.client_admin_a, [self.parent_7a.id], student=other_kid.id)
        self.assertEqual(response.data, NOT_FOUND_STUDENT)
