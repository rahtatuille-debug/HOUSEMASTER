"""
Tests for the guardian-account flow: invite -> accept -> guardian_me,
plus scoping and permission boundaries relative to staff.
"""
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from django.contrib.auth.models import User

from communications.models import Announcement
from gradebook.models import Grade, Subject, Term
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

from .models import Guardian


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


class GuardianStudentPortalTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.year = YearGroup.objects.create(school=self.school_a, name="Year 8")
        self.school_class = SchoolClass.objects.create(year_group=self.year, name="8A")
        self.child = Student.objects.create(
            school=self.school_a, school_class=self.school_class, first_name="Amina", last_name="Otieno"
        )
        self.other_child = Student.objects.create(
            school=self.school_a, first_name="Noah", last_name="Kamau"
        )
        guardian_user = User.objects.create_user(
            username="grace@example.test", email="grace@example.test", password="pass1234"
        )
        self.guardian = Guardian.objects.create(
            user=guardian_user, school=self.school_a, display_name="Grace Otieno"
        )
        self.guardian.students.add(self.child)
        self.guardian_client = self.authed_client(guardian_user)

        subject = Subject.objects.create(school=self.school_a, name="Mathematics")
        term = Term.objects.create(school=self.school_a, name="Term 1 2026")
        self.grade = Grade.objects.create(
            student=self.child, subject=subject, term=term, score=86, max_score=100
        )
        Grade.objects.create(student=self.other_child, subject=subject, term=term, score=72, max_score=100)
        self.report = StudentReport.objects.create(
            student=self.child, term=term, progress_summary="Strong progress.", report_comment="Well done.",
            status="finalized",
        )
        StudentReport.objects.create(
            student=self.other_child, term=term, progress_summary="Private.", report_comment="Private.", status="finalized"
        )

    def test_guardian_can_view_only_linked_children_and_their_grades_reports(self):
        response = self.guardian_client.get("/api/guardian-students/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data], [self.child.id])
        self.assertEqual(response.data[0]["school_class_name"], "Year 8 — 8A")

        grades = self.guardian_client.get(f"/api/guardian-students/{self.child.id}/grades/")
        self.assertEqual(grades.status_code, 200)
        self.assertEqual(grades.data[0]["id"], self.grade.id)
        self.assertEqual(grades.data[0]["subject_name"], "Mathematics")

        reports = self.guardian_client.get(f"/api/guardian-students/{self.child.id}/reports/")
        self.assertEqual(reports.status_code, 200)
        self.assertEqual(reports.data[0]["id"], self.report.id)

        StudentReport.objects.create(
            student=self.child, term=Term.objects.create(school=self.school_a, name="Term 2 2026"),
            progress_summary="Internal draft.", report_comment="Internal draft.", status="draft",
        )
        reports = self.guardian_client.get(f"/api/guardian-students/{self.child.id}/reports/")
        self.assertEqual([item["id"] for item in reports.data], [self.report.id])

    def test_guardian_cannot_view_unlinked_child_or_their_records(self):
        self.assertEqual(
            self.guardian_client.get(f"/api/guardian-students/{self.other_child.id}/").status_code, 404
        )
        self.assertEqual(
            self.guardian_client.get(f"/api/guardian-students/{self.other_child.id}/grades/").status_code, 404
        )

    def test_guardian_sees_only_parent_announcements_for_linked_child(self):
        all_parents = Announcement.objects.create(
            school=self.school_a, title="School closure", body="Friday closes early.",
            audience=Announcement.Audience.ALL_PARENTS, status=Announcement.Status.PUBLISHED,
        )
        year_notice = Announcement.objects.create(
            school=self.school_a, title="Year 8 notice", body="Year 8 update.",
            audience=Announcement.Audience.YEAR_GROUP, year_group=self.year,
            status=Announcement.Status.PUBLISHED,
        )
        class_notice = Announcement.objects.create(
            school=self.school_a, title="8A notice", body="8A update.",
            audience=Announcement.Audience.SCHOOL_CLASS, school_class=self.school_class,
            status=Announcement.Status.PUBLISHED,
        )
        staff_notice = Announcement.objects.create(
            school=self.school_a, title="Staff notice", body="Staff only.",
            audience=Announcement.Audience.ALL_STAFF, status=Announcement.Status.PUBLISHED,
        )

        response = self.guardian_client.get("/api/announcements/")
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data]
        self.assertCountEqual(ids, [all_parents.id, year_notice.id, class_notice.id])
        self.assertNotIn(staff_notice.id, ids)
