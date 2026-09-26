"""
Cross-school isolation: one school must never see, change, or even learn
about the existence of another school's data, through any endpoint,
response format, error message or filter.

These tests take the point of view of an admin at School A (the widest
access a school user has) trying to reach School B's records.
"""
from django.contrib.auth.models import User

from gradebook.models import Grade, Subject, Term
from guardians.models import Guardian
from reporting.models import StudentReport
from students.models import SchoolClass, Student, YearGroup

from .tests import SchoolScopedAPITestCase


class CrossSchoolIsolationTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.make_admin(self.user_a)
        # School B's records, which School A must never reach.
        year_b = YearGroup.objects.create(school=self.school_b, name="Secret Year")
        self.class_b = SchoolClass.objects.create(year_group=year_b, name="Secret Class")
        self.student_b = Student.objects.create(school=self.school_b, first_name="Secret", last_name="Pupil",
                                                school_class=self.class_b)
        self.subject_b = Subject.objects.create(school=self.school_b, name="Secret Subject")
        self.term_b = Term.objects.create(school=self.school_b, name="Secret Term")
        parent_user = User.objects.create_user(username="pb@beta.test", email="pb@beta.test", password="pass1234")
        self.parent_b = Guardian.objects.create(user=parent_user, school=self.school_b, display_name="Secret Parent")
        # School A's own records.
        self.student_a = Student.objects.create(school=self.school_a, first_name="Own", last_name="Pupil")
        self.subject_a = Subject.objects.create(school=self.school_a, name="Maths")
        self.term_a = Term.objects.create(school=self.school_a, name="Term 1")
        self.missing_id = 999999

    # --- writes can't link to another school's records

    def test_report_cannot_use_another_schools_term(self):
        response = self.client_a.post("/api/reports/", {
            "student": self.student_a.id, "term": self.term_b.id,
            "progress_summary": "x", "report_comment": "x",
        })
        self.assertGreaterEqual(response.status_code, 400)
        self.assertFalse(StudentReport.objects.filter(term=self.term_b).exists())

    def test_report_cannot_be_moved_to_another_schools_term(self):
        report = StudentReport.objects.create(student=self.student_a, term=self.term_a,
                                              progress_summary="x", report_comment="x")
        response = self.client_a.patch(f"/api/reports/{report.id}/", {"term": self.term_b.id})
        self.assertGreaterEqual(response.status_code, 400)
        report.refresh_from_db()
        self.assertEqual(report.term, self.term_a)

    # --- another school's IDs look exactly like IDs that don't exist

    def assert_same_as_missing(self, method, url, field, other_school_id, extra=None, fmt=None):
        def call(value):
            body = dict(extra or {}, **{field: value})
            return getattr(self.client_a, method)(url, body, format=fmt)

        missing_value = [self.missing_id] if isinstance(other_school_id, list) else self.missing_id
        real, missing = call(other_school_id), call(missing_value)
        self.assertEqual(real.status_code, missing.status_code,
                         f"{url} {field}: another school's id is distinguishable from a missing one")
        other = other_school_id[0] if isinstance(other_school_id, list) else other_school_id
        self.assertEqual(str(real.data).replace(str(other), "ID"),
                         str(missing.data).replace(str(self.missing_id), "ID"))

    def test_write_errors_dont_reveal_other_schools_records(self):
        self.assert_same_as_missing("post", "/api/grades/", "student", self.student_b.id,
                                    {"subject": self.subject_a.id, "term": self.term_a.id, "score": "1"})
        self.assert_same_as_missing("post", "/api/grades/", "subject", self.subject_b.id,
                                    {"student": self.student_a.id, "term": self.term_a.id, "score": "1"})
        self.assert_same_as_missing("post", "/api/attendance/", "student", self.student_b.id,
                                    {"date": "2026-09-01", "status": "present"})
        self.assert_same_as_missing("post", "/api/reports/", "term", self.term_b.id,
                                    {"student": self.student_a.id, "progress_summary": "x", "report_comment": "x"})
        self.assert_same_as_missing("post", "/api/students/", "school_class", self.class_b.id,
                                    {"first_name": "A", "last_name": "B"})
        self.assert_same_as_missing("post", "/api/teaching-assignments/", "school_class", self.class_b.id,
                                    {"teacher": self.user_a.profile.id})
        self.assert_same_as_missing("post", "/api/teaching-assignments/", "teacher", self.user_b.profile.id,
                                    {"school_class": self.class_b.id})
        self.assert_same_as_missing("post", "/api/guardian-invites/", "students", [self.student_b.id],
                                    {"name": "P", "email": "new-parent@alpha.test"}, fmt="json")
        self.assert_same_as_missing("post", "/api/conversations/", "participant_ids", [self.parent_b.user.id],
                                    {"body": "hi"}, fmt="json")

    def test_filters_dont_reveal_other_schools_records(self):
        for url, field, other_id in [
            ("/api/grades/", "student", self.student_b.id),
            ("/api/grades/", "subject", self.subject_b.id),
            ("/api/attendance/", "student", self.student_b.id),
            ("/api/reports/", "term", self.term_b.id),
            ("/api/students/", "school_class", self.class_b.id),
            ("/api/students/", "school", self.school_b.id),
        ]:
            real = self.client_a.get(url, {field: other_id})
            missing = self.client_a.get(url, {field: self.missing_id})
            self.assertEqual((real.status_code, real.data), (missing.status_code, missing.data), f"{url}?{field}")

    # --- no other response format lists another school's records

    def test_html_api_pages_dont_list_other_schools_records(self):
        secrets = ["Secret Pupil", "Secret Subject", "Secret Term", "Secret Class", "Secret Year",
                   "Secret Parent", "Beta College"]
        for url in ["/api/grades/", "/api/attendance/", "/api/reports/", "/api/students/",
                    "/api/school-classes/", "/api/teaching-assignments/", "/api/guardian-invites/",
                    "/api/announcements/", "/api/parents/", "/api/staff/"]:
            response = self.client_a.get(url, HTTP_ACCEPT="text/html")
            body = response.content.decode()
            for secret in secrets:
                self.assertNotIn(secret, body, f"{url} as HTML shows {secret!r}")

    # --- inviting an email that's already in use elsewhere doesn't reveal it

    def test_staff_invite_doesnt_reveal_accounts_at_other_schools(self):
        other = self.client_a.post("/api/invites/", {"email": "teacher.b@beta.test", "name": "X", "role": "teacher"})
        fresh = self.client_a.post("/api/invites/", {"email": "nobody@nowhere.test", "name": "X", "role": "teacher"})
        self.assertEqual(other.status_code, fresh.status_code)

    def test_parent_invite_doesnt_reveal_accounts_at_other_schools(self):
        body = {"name": "X", "students": [self.student_a.id]}
        other = self.client_a.post("/api/guardian-invites/", dict(body, email="pb@beta.test"), format="json")
        fresh = self.client_a.post("/api/guardian-invites/", dict(body, email="nobody2@nowhere.test"), format="json")
        self.assertEqual(other.status_code, fresh.status_code)

    def test_invite_for_email_used_elsewhere_can_never_be_accepted(self):
        response = self.client_a.post("/api/invites/", {"email": "teacher.b@beta.test", "name": "X", "role": "teacher"})
        from .models import Invite

        invite = Invite.objects.get(id=response.data["id"])
        accept = self.client.post("/api/invites/accept/", {"token": invite.token, "password": "a-long-Password-123"})
        self.assertEqual(accept.status_code, 400)
        self.assertEqual(self.user_b.profile.school, self.school_b)  # untouched
