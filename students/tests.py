"""
Scoping tests for SchoolClassViewSet and StudentViewSet.

Covers: cross-school reads are 404 (not visible at all), creates are
force-scoped to the caller's school regardless of what's in the request
body, and cross-school FK spoofing (e.g. attaching a Student to another
school's SchoolClass) is rejected with 403.
"""
from accounts.tests import SchoolScopedAPITestCase

from .models import YearGroup, SchoolClass, Student


class StudentScopingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.student_a = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno"
        )
        self.student_b = Student.objects.create(
            school=self.school_b, first_name="Brian", last_name="Kiptoo"
        )

    def test_list_only_returns_own_schools_students(self):
        response = self.client_a.get("/api/students/")
        self.assertEqual(response.status_code, 200)
        names = [row["first_name"] for row in response.data]
        self.assertIn("Amina", names)
        self.assertNotIn("Brian", names)

    def test_cannot_retrieve_another_schools_student(self):
        response = self.client_a.get(f"/api/students/{self.student_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_cannot_update_another_schools_student(self):
        response = self.client_a.patch(
            f"/api/students/{self.student_b.id}/", {"first_name": "Hacked"}
        )
        self.assertEqual(response.status_code, 404)
        self.student_b.refresh_from_db()
        self.assertEqual(self.student_b.first_name, "Brian")

    def test_cannot_delete_another_schools_student(self):
        response = self.client_a.delete(f"/api/students/{self.student_b.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Student.objects.filter(id=self.student_b.id).exists())

    def test_create_forces_callers_school_even_if_spoofed(self):
        # Even if a client tries to sneak school_b's ID into the request
        # body, the server must force it back to the caller's own school —
        # this is the "school" read_only-field fix (see project notes) plus
        # the perform_create force-assignment.
        response = self.client_a.post(
            "/api/students/",
            {
                "school": self.school_b.id,
                "first_name": "Carl",
                "last_name": "Njoroge",
            },
        )
        self.assertEqual(response.status_code, 201)
        created = Student.objects.get(id=response.data["id"])
        self.assertEqual(created.school_id, self.school_a.id)

    def test_create_without_school_field_succeeds(self):
        # Mirrors the real frontend, which never sends `school` at all.
        response = self.client_a.post(
            "/api/students/", {"first_name": "Dana", "last_name": "Wanjiru"}
        )
        self.assertEqual(response.status_code, 201)
        created = Student.objects.get(id=response.data["id"])
        self.assertEqual(created.school_id, self.school_a.id)

    def test_cannot_attach_student_to_another_schools_class(self):
        year_group_b = YearGroup.objects.create(school=self.school_b, name="Year 7")
        class_b = SchoolClass.objects.create(year_group=year_group_b, name="7A")

        response = self.client_a.post(
            "/api/students/",
            {"first_name": "Eve", "last_name": "Achieng", "school_class": class_b.id},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Student.objects.filter(first_name="Eve").exists())

    def test_filter_by_is_active_only_touches_own_school(self):
        Student.objects.create(
            school=self.school_a, first_name="Frank", last_name="Mutua", is_active=False
        )
        response = self.client_a.get("/api/students/?is_active=false")
        self.assertEqual(response.status_code, 200)
        names = [row["first_name"] for row in response.data]
        self.assertEqual(names, ["Frank"])


class SchoolClassScopingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.year_group_a = YearGroup.objects.create(school=self.school_a, name="Year 8")
        self.year_group_b = YearGroup.objects.create(school=self.school_b, name="Year 8")
        self.class_a = SchoolClass.objects.create(year_group=self.year_group_a, name="8A")
        self.class_b = SchoolClass.objects.create(year_group=self.year_group_b, name="8A")

    def test_list_only_returns_own_schools_classes(self):
        response = self.client_a.get("/api/school-classes/")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data]
        self.assertIn(self.class_a.id, ids)
        self.assertNotIn(self.class_b.id, ids)

    def test_cannot_create_class_under_another_schools_year_group(self):
        response = self.client_a.post(
            "/api/school-classes/", {"year_group": self.year_group_b.id, "name": "8B"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SchoolClass.objects.filter(name="8B").exists())

    def test_cannot_repoint_existing_class_to_another_schools_year_group(self):
        # class_b already occupies (year_group_b, "8A"), so also send a
        # different name to isolate the scoping check from the unrelated
        # (year_group, name) unique-together constraint.
        response = self.client_a.patch(
            f"/api/school-classes/{self.class_a.id}/",
            {"year_group": self.year_group_b.id, "name": "8A-moved"},
        )
        self.assertEqual(response.status_code, 403)
        self.class_a.refresh_from_db()
        self.assertEqual(self.class_a.year_group_id, self.year_group_a.id)
