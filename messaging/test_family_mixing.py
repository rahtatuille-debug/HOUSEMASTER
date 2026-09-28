"""
B-5: a direct conversation never puts unrelated families together.

Every parent in a direct (non-class) conversation must share at least one
child with every other parent in it, so parents never learn each other's
names by being added to the same thread. Staff wanting to reach unrelated
parents start separate conversations. A refusal gets the same answer as an
ID that doesn't exist (F-01). Class discussions show a class's parents to
each other by design and are unchanged.
"""
from messaging.models import Conversation
from students.models import SchoolClass, Student, YearGroup

from .test_contact_rules import NOT_FOUND_PARTICIPANT, ContactFixture


class FamilyMixingTests(ContactFixture):
    # The F-01 fixtures: school A, 7A taught by user_a, 7B by teacher_7b;
    # parent_7a of kid_7a, parent_7b of kid_7b.
    def setUp(self):
        super().setUp()
        # A second parent of kid_7a (same family), and a parent of a
        # different child in the same class (another family).
        self.parent_7a_second = self.parent("otieno.dad@example.com", "Daniel Otieno", self.kid_7a)
        self.kid_7a_other = Student.objects.create(school=self.school_a, first_name="Chege", last_name="Mwangi",
                                                   school_class=self.class_7a)
        self.parent_other_family = self.parent("wanjiru@example.com", "Wanjiru Mwangi", self.kid_7a_other)
        self.client_teacher = self.client_a  # user_a teaches 7A

    def test_two_parents_of_the_same_child_can_be_in_one_conversation(self):
        response = self.start(self.client_teacher, [self.parent_7a.id, self.parent_7a_second.id],
                              student=self.kid_7a.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["member_count"], 3)

    def test_parents_of_different_children_are_refused_like_unknown_ids(self):
        mixed = self.start(self.client_teacher, [self.parent_7a.id, self.parent_other_family.id])
        unknown = self.start(self.client_teacher, [self.parent_7a.id, 999999])
        self.assertEqual(mixed.status_code, 400)
        self.assertEqual(mixed.data, NOT_FOUND_PARTICIPANT)
        self.assertEqual(mixed.json(), unknown.json())
        self.assertFalse(Conversation.objects.filter(kind=Conversation.Kind.DIRECT).exists())

    def test_admins_cannot_mix_families_either(self):
        response = self.start(self.client_admin_a, [self.parent_7a.id, self.parent_7b.id])
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

    def test_one_unrelated_parent_among_related_ones_is_refused(self):
        response = self.start(self.client_teacher,
                              [self.parent_7a.id, self.parent_7a_second.id, self.parent_other_family.id])
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

    def test_parents_of_siblings_share_a_child_and_are_allowed(self):
        # Step-parents: each linked to a different sibling and both to the youngest.
        youngest = Student.objects.create(school=self.school_a, first_name="Zawadi", last_name="Otieno",
                                          school_class=self.class_7a)
        self.parent_7a.guardian.students.add(youngest)
        self.parent_other_family.guardian.students.add(youngest)
        response = self.start(self.client_teacher, [self.parent_7a.id, self.parent_other_family.id])
        self.assertEqual(response.status_code, 201, response.data)

    def test_parent_with_staff_is_unaffected(self):
        response = self.start(self.client_teacher, [self.parent_7a.id, self.admin_a.id, self.teacher_7b.id])
        self.assertEqual(response.status_code, 201, response.data)
        parent_side = self.start(self.client_parent_7a, [self.user_a.id, self.admin_a.id])
        self.assertEqual(parent_side.status_code, 201, parent_side.data)

    def test_one_parent_on_their_own_is_unaffected(self):
        childless = self.parent("nochild@example.com", "No Child")
        response = self.start(self.client_admin_a, [childless.id])
        self.assertEqual(response.status_code, 201, response.data)

    def test_no_way_to_add_a_parent_to_a_direct_conversation_afterwards(self):
        created = self.start(self.client_teacher, [self.parent_7a.id])
        conversation_id = created.data["id"]
        for method in ("patch", "put"):
            response = getattr(self.client_teacher, method)(
                f"/api/conversations/{conversation_id}/", {"participant_ids": [self.parent_other_family.id]},
                format="json")
            self.assertEqual(response.status_code, 405)
        self.client_teacher.post(f"/api/conversations/{conversation_id}/messages/",
                                 {"body": "Hi", "participant_ids": [self.parent_other_family.id]}, format="json")
        members = set(Conversation.objects.get(id=conversation_id).participants.values_list("id", flat=True))
        self.assertEqual(members, {self.user_a.id, self.parent_7a.id})

    def test_class_discussions_still_include_every_parent_of_the_class(self):
        response = self.client_teacher.post("/api/conversations/class/", {
            "school_class": self.class_7a.id, "kind": Conversation.Kind.CLASS_GROUP, "body": "Trip on Friday"},
            format="json")
        self.assertEqual(response.status_code, 201, response.data)
        members = set(Conversation.objects.get(id=response.data["id"]).participants.values_list("id", flat=True))
        self.assertTrue({self.parent_7a.id, self.parent_7a_second.id, self.parent_other_family.id} <= members)

    def test_parent_at_another_school_is_refused(self):
        year_b = YearGroup.objects.create(school=self.school_b, name="Y")
        kid_b = Student.objects.create(school=self.school_b, first_name="B", last_name="Kid",
                                       school_class=SchoolClass.objects.create(year_group=year_b, name="B1"))
        parent_b = self.parent("b.parent@example.com", "B Parent", kid_b, school=self.school_b)
        response = self.start(self.client_admin_a, [self.parent_7a.id, parent_b.id])
        self.assertEqual(response.data, NOT_FOUND_PARTICIPANT)

