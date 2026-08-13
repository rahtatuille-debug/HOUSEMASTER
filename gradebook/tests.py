"""
Scoping tests for SubjectViewSet, TermViewSet, and GradeViewSet.

Grade is the most important case here: it doesn't have its own `school`
field at all (school_lookup = "student__school"), and perform_create /
perform_update validate all three of student, subject, and term
independently — so a spoofed cross-school ID on any one of the three
should be rejected.
"""
from students.models import Student
from accounts.tests import SchoolScopedAPITestCase

from .models import Subject, Term, Grade


class SubjectScopingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.subject_a = Subject.objects.create(school=self.school_a, name="Mathematics")
        self.subject_b = Subject.objects.create(school=self.school_b, name="Mathematics")

    def test_list_only_returns_own_schools_subjects(self):
        response = self.client_a.get("/api/subjects/")
        ids = [row["id"] for row in response.data]
        self.assertIn(self.subject_a.id, ids)
        self.assertNotIn(self.subject_b.id, ids)

    def test_create_forces_callers_school(self):
        response = self.client_a.post(
            "/api/subjects/", {"school": self.school_b.id, "name": "Chemistry"}
        )
        self.assertEqual(response.status_code, 201)
        created = Subject.objects.get(id=response.data["id"])
        self.assertEqual(created.school_id, self.school_a.id)

    def test_cannot_retrieve_or_delete_another_schools_subject(self):
        response = self.client_a.get(f"/api/subjects/{self.subject_b.id}/")
        self.assertEqual(response.status_code, 404)
        response = self.client_a.delete(f"/api/subjects/{self.subject_b.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Subject.objects.filter(id=self.subject_b.id).exists())


class TermScopingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.term_a = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.term_b = Term.objects.create(school=self.school_b, name="Term 1 2026")

    def test_list_only_returns_own_schools_terms(self):
        response = self.client_a.get("/api/terms/")
        ids = [row["id"] for row in response.data]
        self.assertIn(self.term_a.id, ids)
        self.assertNotIn(self.term_b.id, ids)

    def test_create_forces_callers_school(self):
        response = self.client_a.post(
            "/api/terms/", {"school": self.school_b.id, "name": "Term 2 2026"}
        )
        self.assertEqual(response.status_code, 201)
        created = Term.objects.get(id=response.data["id"])
        self.assertEqual(created.school_id, self.school_a.id)


class GradeScopingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.student_a = Student.objects.create(
            school=self.school_a, first_name="Amina", last_name="Otieno"
        )
        self.student_b = Student.objects.create(
            school=self.school_b, first_name="Brian", last_name="Kiptoo"
        )
        self.subject_a = Subject.objects.create(school=self.school_a, name="Mathematics")
        self.subject_b = Subject.objects.create(school=self.school_b, name="Mathematics")
        self.term_a = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.term_b = Term.objects.create(school=self.school_b, name="Term 1 2026")

        self.grade_a = Grade.objects.create(
            student=self.student_a, subject=self.subject_a, term=self.term_a, score=80
        )
        self.grade_b = Grade.objects.create(
            student=self.student_b, subject=self.subject_b, term=self.term_b, score=70
        )

    def test_list_only_returns_own_schools_grades(self):
        response = self.client_a.get("/api/grades/")
        ids = [row["id"] for row in response.data]
        self.assertIn(self.grade_a.id, ids)
        self.assertNotIn(self.grade_b.id, ids)

    def test_cannot_retrieve_another_schools_grade(self):
        response = self.client_a.get(f"/api/grades/{self.grade_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_create_rejects_spoofed_student(self):
        response = self.client_a.post(
            "/api/grades/",
            {
                "student": self.student_b.id,
                "subject": self.subject_a.id,
                "term": self.term_a.id,
                "score": 90,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_create_rejects_spoofed_subject(self):
        response = self.client_a.post(
            "/api/grades/",
            {
                "student": self.student_a.id,
                "subject": self.subject_b.id,
                "term": self.term_a.id,
                "score": 90,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_create_rejects_spoofed_term(self):
        response = self.client_a.post(
            "/api/grades/",
            {
                "student": self.student_a.id,
                "subject": self.subject_a.id,
                "term": self.term_b.id,
                "score": 90,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_create_succeeds_when_all_three_belong_to_caller(self):
        response = self.client_a.post(
            "/api/grades/",
            {
                "student": self.student_a.id,
                "subject": self.subject_a.id,
                "term": self.term_a.id,
                "score": 95,
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_update_rejects_repointing_to_another_schools_student(self):
        response = self.client_a.patch(
            f"/api/grades/{self.grade_a.id}/", {"student": self.student_b.id}
        )
        self.assertEqual(response.status_code, 403)
        self.grade_a.refresh_from_db()
        self.assertEqual(self.grade_a.student_id, self.student_a.id)

    def test_filter_by_student_across_schools_returns_nothing(self):
        # Filtering by another school's student ID should behave like the
        # student doesn't exist for this caller, not error or leak data.
        response = self.client_a.get(f"/api/grades/?student={self.student_b.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)
