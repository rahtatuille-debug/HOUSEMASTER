"""
Staff may only message parents about those parents' own children (owner's
request, 2026-10-07). A conversation with a parent can name one of that
parent's children, never another family's child, even one the teacher
teaches. The "new message" picker lists each parent's children, so the
child dropdown only offers theirs.
"""
from students.models import Student

from .test_contact_rules import NOT_FOUND_STUDENT, ContactFixture


class AboutTheirChildTests(ContactFixture):
    def setUp(self):
        super().setUp()
        # Another family in 7A: user_a teaches both children.
        self.kid_7a_other = Student.objects.create(school=self.school_a, first_name="Zuri", last_name="Mwangi",
                                                   school_class=self.class_7a)
        self.parent_7a_other = self.parent("zuri.parent@example.com", "Ann Mwangi", self.kid_7a_other)

    def test_teacher_cannot_message_a_parent_about_another_familys_child(self):
        response = self.start(self.client_a, [self.parent_7a.id], student=self.kid_7a_other.id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, NOT_FOUND_STUDENT)

    def test_admin_cannot_either(self):
        response = self.start(self.client_admin_a, [self.parent_7a.id], student=self.kid_7b.id)
        self.assertEqual(response.data, NOT_FOUND_STUDENT)

    def test_their_own_child_is_fine(self):
        response = self.start(self.client_a, [self.parent_7a.id], student=self.kid_7a.id)
        self.assertEqual(response.status_code, 201, response.data)

    def test_staff_to_staff_may_still_name_a_pupil(self):
        response = self.start(self.client_admin_a, [self.user_a.id], student=self.kid_7a.id)
        self.assertEqual(response.status_code, 201, response.data)

    def test_contacts_list_each_parents_children_that_the_caller_can_see(self):
        both = self.parent("both@example.com", "Both Kids", self.kid_7a_other, self.kid_7b)
        rows = {r["id"]: r for r in self.client_a.get("/api/conversations/contacts/").json()}
        self.assertEqual(rows[self.parent_7a.id]["children"], [{"id": self.kid_7a.id, "name": "Amina Otieno"}])
        # user_a doesn't teach 7B, so that child isn't named to them.
        self.assertEqual(rows[both.id]["children"], [{"id": self.kid_7a_other.id, "name": "Zuri Mwangi"}])
        admin_rows = {r["id"]: r for r in self.client_admin_a.get("/api/conversations/contacts/").json()}
        self.assertEqual({c["name"] for c in admin_rows[both.id]["children"]}, {"Zuri Mwangi", "Brian Kamau"})

    def test_parents_contacts_have_no_children_list(self):
        rows = self.client_parent_7a.get("/api/conversations/contacts/").json()
        self.assertTrue(rows)
        self.assertTrue(all("children" not in r for r in rows))
