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
        self.make_admin(self.user_a, self.user_b)
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
        # Another school's record is rejected exactly like one that doesn't exist.
        self.assertEqual(response.status_code, 400)
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
        self.make_admin(self.user_a, self.user_b)
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
        # Another school's record is rejected exactly like one that doesn't exist.
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SchoolClass.objects.filter(name="8B").exists())

    def test_cannot_repoint_existing_class_to_another_schools_year_group(self):
        # class_b already occupies (year_group_b, "8A"), so also send a
        # different name to isolate the scoping check from the unrelated
        # (year_group, name) unique-together constraint.
        response = self.client_a.patch(
            f"/api/school-classes/{self.class_a.id}/",
            {"year_group": self.year_group_b.id, "name": "8A-moved"},
        )
        # Another school's record is rejected exactly like one that doesn't exist.
        self.assertEqual(response.status_code, 400)
        self.class_a.refresh_from_db()
        self.assertEqual(self.class_a.year_group_id, self.year_group_a.id)


class StudentProfileTests(SchoolScopedAPITestCase):
    """The student profile page: its summary and the student's photo."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User

        from attendance.models import AttendanceRecord
        from gradebook.models import Grade, Subject, Term
        from guardians.models import Guardian

        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.class_7a = SchoolClass.objects.create(year_group=year, name="7A")
        class_7b = SchoolClass.objects.create(year_group=year, name="7B")
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        term = Term.objects.create(school=self.school_a, name="Term 1", start_date="2026-01-01", end_date="2026-04-01")
        self.student = Student.objects.create(
            school=self.school_a, first_name="John", last_name="Doe", school_class=self.class_7a,
            external_id="BS2068", gender="male", date_of_birth="2014-01-01", mode_of_learning="day",
            medical_notes="Peanut allergy",
        )
        classmate = Student.objects.create(school=self.school_a, first_name="Ann", last_name="Mate",
                                           school_class=self.class_7a)
        other = Student.objects.create(school=self.school_a, first_name="Ben", last_name="Other",
                                       school_class=class_7b)
        Grade.objects.create(student=self.student, subject=self.maths, term=term, score=80)
        Grade.objects.create(student=classmate, subject=self.maths, term=term, score=60)
        Grade.objects.create(student=other, subject=self.maths, term=term, score=40)
        AttendanceRecord.objects.create(student=self.student, date="2026-02-02", status="present")
        AttendanceRecord.objects.create(student=self.student, date="2026-02-03", status="absent")
        parent_user = User.objects.create_user(username="pd@x.test", email="pd@x.test", password="pass1234")
        Guardian.objects.create(user=parent_user, school=self.school_a, display_name="Jane Doe").students.add(self.student)
        self.assign(self.user_a, self.class_7a, self.maths)

    def test_profile_brings_everything_together(self):
        data = self.admin_client_a.get(f"/api/students/{self.student.id}/profile/").data
        self.assertEqual(data["student"]["external_id"], "BS2068")
        self.assertEqual(data["student"]["medical_notes"], "Peanut allergy")
        self.assertEqual(data["class_name"], "7A")
        self.assertEqual(data["year_group_name"], "Year 7")
        self.assertEqual(data["teachers"], [{"teacher": self.user_a.profile.name, "subject": "Maths"}])
        self.assertEqual(data["parents"][0]["name"], "Jane Doe")
        self.assertEqual(data["performance"], [{"term": "Term 1", "student": 80.0, "class": 70.0, "year_group": 60.0}])
        self.assertEqual(data["attendance"]["overall"]["total"], 2)
        self.assertEqual(data["attendance"]["overall"]["rate"], 50.0)
        self.assertEqual(data["grades_by_term"][0]["grades"][0]["percent"], 80.0)
        self.assertIsInstance(data["activity"], list)  # admins get the student's history

    def test_teacher_sees_own_students_profile_without_activity_history(self):
        data = self.client_a.get(f"/api/students/{self.student.id}/profile/").data
        self.assertEqual(data["class_name"], "7A")
        self.assertIsNone(data["activity"])

    def test_teacher_cannot_see_profile_outside_their_classes(self):
        other = Student.objects.get(first_name="Ben")
        self.assertEqual(self.client_a.get(f"/api/students/{other.id}/profile/").status_code, 404)

    def test_other_school_cannot_see_profile_or_photo(self):
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get(f"/api/students/{self.student.id}/profile/").status_code, 404)
        self.assertEqual(self.client_b.get(f"/api/students/{self.student.id}/photo/").status_code, 404)

    def _image(self, fmt="PNG", size=(900, 600)):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", size, (200, 30, 30)).save(buf, format=fmt)
        return SimpleUploadedFile(f"photo.{fmt.lower()}", buf.getvalue(), content_type=f"image/{fmt.lower()}")

    def test_photo_upload_is_squared_and_served_as_jpeg(self):
        from io import BytesIO

        from PIL import Image

        response = self.client_a.post(f"/api/students/{self.student.id}/photo/", {"photo": self._image()},
                                      format="multipart")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["has_photo"])
        photo = self.client_a.get(f"/api/students/{self.student.id}/photo/")
        self.assertEqual(photo["Content-Type"], "image/jpeg")
        self.assertEqual(Image.open(BytesIO(photo.content)).size, (400, 400))

    def test_non_image_upload_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        fake = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        response = self.client_a.post(f"/api/students/{self.student.id}/photo/", {"photo": fake}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_photo_can_be_removed(self):
        self.client_a.post(f"/api/students/{self.student.id}/photo/", {"photo": self._image()}, format="multipart")
        self.assertEqual(self.client_a.delete(f"/api/students/{self.student.id}/photo/").status_code, 200)
        self.assertEqual(self.client_a.get(f"/api/students/{self.student.id}/photo/").status_code, 404)

    def test_new_detail_fields_can_be_edited(self):
        response = self.client_a.patch(f"/api/students/{self.student.id}/", {
            "nationality": "Kenyan", "mode_of_learning": "boarding", "gender": "male",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["mode_of_learning"], "boarding")
