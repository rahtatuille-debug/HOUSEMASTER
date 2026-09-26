"""
Tests for the accounts app: HasSchoolProfile permission, /api/me/, and the
SchoolViewSet itself (School is the one model that IS the tenant, rather
than reaching it via school_lookup).

This module also defines SchoolScopedAPITestCase, a shared base class used
by every other app's test suite (students, gradebook, attendance,
reporting). It exists here — rather than in a separate, non-test-ish file —
so Django's test discovery picks it up naturally and every app can just
`from accounts.tests import SchoolScopedAPITestCase` without an extra
import path to remember.

Run the whole suite with:
    python manage.py test

Run just this file with:
    python manage.py test accounts
"""
from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from activity.models import ActivityLog
from students.models import School
from .models import Invite, PasswordResetToken, Profile


class SchoolScopedAPITestCase(APITestCase):
    """
    Sets up two separate schools, each with one authenticated staff user,
    so every scoping test can assert that School A's client can see/act on
    School A's data and never School B's — and vice versa.

    Subclasses can add their own setUp() but MUST call
    super().setUp() first to get self.school_a / self.school_b /
    self.user_a / self.user_b / self.client_a / self.client_b.
    """

    def setUp(self):
        self.school_a = School.objects.create(name="Alpha Academy", report_tone="formal")
        self.school_b = School.objects.create(name="Beta College", report_tone="warm")

        self.user_a = User.objects.create_user(
            username="teacher_a", email="teacher.a@alpha.test", password="pass1234"
        )
        Profile.objects.create(user=self.user_a, school=self.school_a, role=Profile.Role.TEACHER)

        self.user_b = User.objects.create_user(
            username="teacher_b", email="teacher.b@beta.test", password="pass1234"
        )
        Profile.objects.create(user=self.user_b, school=self.school_b, role=Profile.Role.TEACHER)

        self.admin_a = User.objects.create_user(
            username="admin_a", email="admin.a@alpha.test", password="pass1234"
        )
        Profile.objects.create(user=self.admin_a, school=self.school_a, role=Profile.Role.ADMIN)

        self.client_a = self.authed_client(self.user_a)
        self.client_b = self.authed_client(self.user_b)

    @staticmethod
    def make_admin(*users):
        """
        Scoping tests that check one school can't reach another's data use
        admins, who see everything at their own school, so that teacher
        class assignments don't hide the rows under test.
        """
        for user in users:
            user.profile.role = Profile.Role.ADMIN
            user.profile.save(update_fields=["role"])

    @staticmethod
    def assign(user, school_class, subject):
        """Assign a teacher to teach `subject` to `school_class`."""
        from .models import TeachingAssignment

        return TeachingAssignment.objects.create(
            teacher=user.profile, school_class=school_class, subject=subject
        )

    @staticmethod
    def authed_client(user):
        from rest_framework.test import APIClient

        client = APIClient()
        token = RefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        return client


class HasSchoolProfilePermissionTests(SchoolScopedAPITestCase):
    def test_unauthenticated_request_is_401(self):
        from rest_framework.test import APIClient

        response = APIClient().get("/api/students/")
        self.assertEqual(response.status_code, 401)

    def test_authenticated_without_profile_is_403(self):
        from rest_framework.test import APIClient

        bare_user = User.objects.create_user(username="no_profile", password="pass1234")
        client = self.authed_client(bare_user)
        response = client.get("/api/students/")
        self.assertEqual(response.status_code, 403)

    def test_authenticated_with_profile_is_allowed(self):
        response = self.client_a.get("/api/students/")
        self.assertEqual(response.status_code, 200)


class MeEndpointTests(SchoolScopedAPITestCase):
    def test_me_returns_own_name_role_and_school(self):
        self.user_a.profile.display_name = "Amina Otieno"
        self.user_a.profile.save(update_fields=["display_name"])
        response = self.client_a.get("/api/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Amina Otieno")
        self.assertNotIn("email", response.data)
        self.assertEqual(response.data["role"], "teacher")
        self.assertEqual(response.data["school"]["id"], self.school_a.id)
        self.assertEqual(response.data["school"]["name"], "Alpha Academy")

    def test_me_never_leaks_other_schools_data(self):
        response = self.client_a.get("/api/me/")
        self.assertNotEqual(response.data["school"]["id"], self.school_b.id)

    def test_me_allows_staff_to_update_their_display_name(self):
        response = self.client_a.patch("/api/me/", {"name": "Amina Otieno"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Amina Otieno")
        self.user_a.profile.refresh_from_db()
        self.assertEqual(self.user_a.profile.display_name, "Amina Otieno")


class SchoolViewSetScopingTests(SchoolScopedAPITestCase):
    """
    School is the one model that IS the tenant (school_lookup doesn't apply
    the normal way — see SchoolViewSet.get_queryset), so it gets its own
    explicit coverage rather than relying on the generic mixin tests below.
    """

    def setUp(self):
        super().setUp()
        self.make_admin(self.user_a, self.user_b)

    def test_list_only_returns_own_school(self):
        response = self.client_a.get("/api/schools/")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data]
        self.assertEqual(ids, [self.school_a.id])

    def test_cannot_retrieve_another_schools_row(self):
        response = self.client_a.get(f"/api/schools/{self.school_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_can_update_own_school(self):
        response = self.client_a.patch(
            f"/api/schools/{self.school_a.id}/", {"report_tone": "concise"}
        )
        self.assertEqual(response.status_code, 200)
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.report_tone, "concise")

    def test_cannot_update_another_schools_row(self):
        response = self.client_a.patch(
            f"/api/schools/{self.school_b.id}/", {"report_tone": "concise"}
        )
        self.assertEqual(response.status_code, 404)
        self.school_b.refresh_from_db()
        self.assertEqual(self.school_b.report_tone, "warm")

    def test_cannot_create_or_delete_schools_via_api(self):
        # SchoolViewSet.http_method_names excludes post/delete on purpose.
        response = self.client_a.post("/api/schools/", {"name": "New School"})
        self.assertEqual(response.status_code, 405)

        response = self.client_a.delete(f"/api/schools/{self.school_a.id}/")
        self.assertEqual(response.status_code, 405)


class PasswordResetTests(SchoolScopedAPITestCase):
    def test_request_with_known_email_sends_email_and_creates_token(self):
        response = self.client.post("/api/password-reset/", {"email": self.user_a.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetToken.objects.filter(user=self.user_a).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user_a.email, mail.outbox[0].to)

    def test_request_with_unknown_email_still_returns_200_and_sends_nothing(self):
        response = self.client.post("/api/password-reset/", {"email": "nobody@nowhere.test"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetToken.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_request_with_blank_email_is_a_validation_error(self):
        response = self.client.post("/api/password-reset/", {"email": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PasswordResetToken.objects.count(), 0)

    def test_request_matches_every_account_sharing_that_email(self):
        # User.email has no uniqueness constraint, so a shared address
        # should get a reset link for each account that uses it.
        self.user_b.email = self.user_a.email
        self.user_b.save(update_fields=["email"])
        response = self.client.post("/api/password-reset/", {"email": self.user_a.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PasswordResetToken.objects.filter(user=self.user_a).count(), 1)
        self.assertEqual(PasswordResetToken.objects.filter(user=self.user_b).count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_confirm_with_valid_token_changes_password_and_consumes_token(self):
        reset_token = PasswordResetToken.objects.create(user=self.user_a)
        response = self.client.post(
            "/api/password-reset/confirm/",
            {"token": reset_token.token, "password": "a-brand-new-strong-pw9"},
        )
        self.assertEqual(response.status_code, 200)
        self.user_a.refresh_from_db()
        self.assertTrue(self.user_a.check_password("a-brand-new-strong-pw9"))
        reset_token.refresh_from_db()
        self.assertIsNotNone(reset_token.used_at)

    def test_confirm_rejects_reused_token(self):
        reset_token = PasswordResetToken.objects.create(user=self.user_a)
        self.client.post(
            "/api/password-reset/confirm/",
            {"token": reset_token.token, "password": "a-brand-new-strong-pw9"},
        )
        response = self.client.post(
            "/api/password-reset/confirm/",
            {"token": reset_token.token, "password": "another-strong-pw123"},
        )
        self.assertEqual(response.status_code, 400)

    def test_confirm_rejects_unknown_token(self):
        response = self.client.post(
            "/api/password-reset/confirm/",
            {"token": "not-a-real-token", "password": "a-brand-new-strong-pw9"},
        )
        self.assertEqual(response.status_code, 400)


class LoginTests(SchoolScopedAPITestCase):
    def test_login_with_email_and_password_succeeds(self):
        response = self.client.post(
            "/api/token/", {"email": self.user_a.email, "password": "pass1234"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_with_wrong_password_fails(self):
        response = self.client.post(
            "/api/token/", {"email": self.user_a.email, "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 401)

    def test_login_with_username_field_instead_of_email_fails(self):
        # `username` is no longer accepted by this endpoint at all — only
        # `email` is a recognised field now.
        response = self.client.post(
            "/api/token/", {"username": self.user_a.username, "password": "pass1234"}
        )
        self.assertEqual(response.status_code, 400)

    def test_login_is_case_insensitive_on_email(self):
        response = self.client.post(
            "/api/token/", {"email": self.user_a.email.upper(), "password": "pass1234"}
        )
        self.assertEqual(response.status_code, 200)


class AcceptInviteTests(SchoolScopedAPITestCase):
    def _create_invite(self, email="new.teacher@alpha.test"):
        from .models import Invite

        return Invite.objects.create(
            school=self.school_a,
            role=Profile.Role.TEACHER,
            email=email,
            invited_by=self.admin_a,
        )

    def test_accept_with_valid_token_creates_account_with_invites_email(self):
        invite = self._create_invite()
        response = self.client.post(
            "/api/invites/accept/", {"token": invite.token, "password": "a-strong-new-pw9"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("access", response.data)

        user = User.objects.get(email="new.teacher@alpha.test")
        self.assertTrue(user.check_password("a-strong-new-pw9"))
        self.assertEqual(user.profile.school, self.school_a)
        self.assertEqual(user.profile.role, Profile.Role.TEACHER)

        invite.refresh_from_db()
        self.assertTrue(invite.is_accepted)
        self.assertEqual(invite.accepted_by, user)

    def test_accept_does_not_let_invitee_choose_a_different_email(self):
        # There's no `email`/`username` field on this endpoint at all —
        # the account's email always comes from the invite itself.
        invite = self._create_invite()
        response = self.client.post(
            "/api/invites/accept/",
            {"token": invite.token, "email": "someone-else@alpha.test", "password": "a-strong-new-pw9"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(email="new.teacher@alpha.test").exists())
        self.assertFalse(User.objects.filter(email="someone-else@alpha.test").exists())

    def test_accept_rejects_reused_token(self):
        invite = self._create_invite()
        self.client.post("/api/invites/accept/", {"token": invite.token, "password": "a-strong-new-pw9"})
        response = self.client.post(
            "/api/invites/accept/", {"token": invite.token, "password": "another-strong-pw2"}
        )
        self.assertEqual(response.status_code, 400)

    def test_accept_rejects_email_already_in_use(self):
        invite = self._create_invite(email=self.user_a.email)
        response = self.client.post(
            "/api/invites/accept/", {"token": invite.token, "password": "a-strong-new-pw9"}
        )
        self.assertEqual(response.status_code, 400)


class CheckDuplicateEmailsCommandTests(TestCase):
    """The pre-flight report for adding unique=True to User.email."""

    def run_command(self):
        out = StringIO()
        call_command("check_duplicate_emails", stdout=out)
        return out.getvalue()

    def test_clean_data_reports_nothing(self):
        User.objects.create_user(username="a", email="a@x.test")
        User.objects.create_user(username="b", email="b@x.test")

        output = self.run_command()

        self.assertIn("No duplicate emails.", output)
        self.assertIn("No accounts without an email.", output)

    def test_reports_case_insensitive_duplicates(self):
        # EmailBackend matches with email__iexact, so these two collide.
        u1 = User.objects.create_user(username="first", email="Same@X.test")
        u2 = User.objects.create_user(username="second", email="same@x.test")
        User.objects.create_user(username="other", email="other@x.test")

        output = self.run_command()

        self.assertIn("1 email(s) shared by multiple accounts", output)
        self.assertIn("same@x.test", output)
        self.assertIn(f"id={u1.pk}", output)
        self.assertIn(f"id={u2.pk}", output)
        self.assertNotIn("other@x.test", output)

    def test_reports_accounts_without_email(self):
        u = User.objects.create_user(username="no_email", email="")

        output = self.run_command()

        self.assertIn("1 account(s) with no email", output)
        self.assertIn(f"id={u.pk} username='no_email'", output)

    def test_changes_nothing(self):
        User.objects.create_user(username="first", email="dup@x.test")
        User.objects.create_user(username="second", email="dup@x.test")
        before = list(User.objects.order_by("id").values_list("id", "username", "email"))

        self.run_command()

        after = list(User.objects.order_by("id").values_list("id", "username", "email"))
        self.assertEqual(before, after)


class StaffManagementTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)
        self.profile_a = self.user_a.profile

    def test_admin_lists_only_own_schools_staff(self):
        response = self.admin_client_a.get("/api/staff/")
        self.assertEqual(response.status_code, 200)
        emails = {row["email"] for row in response.data}
        self.assertEqual(emails, {"teacher.a@alpha.test", "admin.a@alpha.test"})

    def test_teacher_cannot_list_or_change_staff(self):
        self.assertEqual(self.client_a.get("/api/staff/").status_code, 403)
        response = self.client_a.patch(f"/api/staff/{self.profile_a.id}/", {"role": "admin"})
        self.assertEqual(response.status_code, 403)

    def test_cannot_touch_another_schools_staff(self):
        other = self.user_b.profile
        self.assertEqual(self.admin_client_a.patch(f"/api/staff/{other.id}/", {"role": "admin"}).status_code, 404)
        self.assertEqual(self.admin_client_a.post(f"/api/staff/{other.id}/deactivate/").status_code, 404)

    def test_admin_changes_role_and_it_is_logged(self):
        response = self.admin_client_a.patch(f"/api/staff/{self.profile_a.id}/", {"role": "admin"})
        self.assertEqual(response.status_code, 200)
        self.profile_a.refresh_from_db()
        self.assertEqual(self.profile_a.role, "admin")
        self.assertTrue(ActivityLog.objects.filter(action="staff.role_changed", target_id=self.profile_a.id).exists())

    def test_invalid_role_rejected(self):
        response = self.admin_client_a.patch(f"/api/staff/{self.profile_a.id}/", {"role": "owner"})
        self.assertEqual(response.status_code, 400)

    def test_only_admin_cannot_demote_or_deactivate_themselves(self):
        own = self.admin_a.profile
        self.assertEqual(self.admin_client_a.patch(f"/api/staff/{own.id}/", {"role": "teacher"}).status_code, 400)
        self.assertEqual(self.admin_client_a.post(f"/api/staff/{own.id}/deactivate/").status_code, 400)

    def test_admin_can_remove_another_admin(self):
        # There's always at least one active admin left: the one acting.
        self.admin_client_a.patch(f"/api/staff/{self.profile_a.id}/", {"role": "admin"})
        response = self.admin_client_a.patch(f"/api/staff/{self.profile_a.id}/", {"role": "teacher"})
        self.assertEqual(response.status_code, 200)
        self.admin_client_a.patch(f"/api/staff/{self.profile_a.id}/", {"role": "admin"})
        response = self.admin_client_a.post(f"/api/staff/{self.profile_a.id}/deactivate/")
        self.assertEqual(response.status_code, 200)

    def test_deactivated_staff_are_locked_out_immediately(self):
        response = self.admin_client_a.post(f"/api/staff/{self.profile_a.id}/deactivate/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        # Their existing login token stops working...
        self.assertEqual(self.client_a.get("/api/me/").status_code, 401)
        # ...they can't log in again...
        login = self.client.post("/api/token/", {"email": "teacher.a@alpha.test", "password": "pass1234"})
        self.assertEqual(login.status_code, 401)
        # ...and their refresh token can't mint a new access token.
        refresh = RefreshToken.for_user(self.user_a)
        self.assertEqual(self.client.post("/api/token/refresh/", {"refresh": str(refresh)}).status_code, 401)
        self.assertTrue(ActivityLog.objects.filter(action="staff.deactivated").exists())

    def test_reactivated_staff_can_log_in_again(self):
        self.admin_client_a.post(f"/api/staff/{self.profile_a.id}/deactivate/")
        self.admin_client_a.post(f"/api/staff/{self.profile_a.id}/reactivate/")
        login = self.client.post("/api/token/", {"email": "teacher.a@alpha.test", "password": "pass1234"})
        self.assertEqual(login.status_code, 200)

    def test_staff_cannot_be_created_directly(self):
        response = self.admin_client_a.post("/api/staff/", {"role": "admin"})
        self.assertEqual(response.status_code, 405)


class TeacherAssignmentScopingTests(SchoolScopedAPITestCase):
    """
    Teachers only see students in classes they're assigned to, and only
    add or change grades for the subjects they teach there. Admins see
    everything at their school.
    """

    def setUp(self):
        super().setUp()
        from gradebook.models import Grade, Subject, Term
        from guardians.models import Guardian
        from students.models import SchoolClass, Student, YearGroup

        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.class_7a = SchoolClass.objects.create(year_group=year, name="7A")
        self.class_7b = SchoolClass.objects.create(year_group=year, name="7B")
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.art = Subject.objects.create(school=self.school_a, name="Art")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.mine = Student.objects.create(school=self.school_a, first_name="In", last_name="Seven-A",
                                           school_class=self.class_7a)
        self.not_mine = Student.objects.create(school=self.school_a, first_name="In", last_name="Seven-B",
                                               school_class=self.class_7b)
        self.art_grade = Grade.objects.create(student=self.mine, subject=self.art, term=self.term, score=50)
        self.other_class_grade = Grade.objects.create(student=self.not_mine, subject=self.maths,
                                                      term=self.term, score=50)
        self.assign(self.user_a, self.class_7a, self.maths)

        def parent(email, child):
            user = User.objects.create_user(username=email, email=email, password="pass1234")
            guardian = Guardian.objects.create(user=user, school=self.school_a, display_name=email)
            guardian.students.add(child)
            return user

        self.my_parent = parent("mine@parent.test", self.mine)
        self.other_parent = parent("other@parent.test", self.not_mine)

    # --- assignments endpoint

    def test_admin_creates_assignment_and_teacher_sees_it_in_me(self):
        response = self.admin_client_a.post("/api/teaching-assignments/", {
            "teacher": self.user_a.profile.id, "school_class": self.class_7b.id, "subject": self.art.id,
        })
        self.assertEqual(response.status_code, 201)
        me = self.client_a.get("/api/me/").data
        self.assertEqual({(a["class_name"], a["subject_name"]) for a in me["assignments"]},
                         {("7A", "Maths"), ("7B", "Art")})
        self.assertTrue(ActivityLog.objects.filter(action="assignment.created").exists())

    def test_teacher_cannot_manage_assignments(self):
        response = self.client_a.post("/api/teaching-assignments/", {
            "teacher": self.user_a.profile.id, "school_class": self.class_7b.id, "subject": self.art.id,
        })
        self.assertEqual(response.status_code, 403)

    def test_duplicate_assignment_rejected(self):
        response = self.admin_client_a.post("/api/teaching-assignments/", {
            "teacher": self.user_a.profile.id, "school_class": self.class_7a.id, "subject": self.maths.id,
        })
        self.assertEqual(response.status_code, 400)

    def test_cannot_assign_another_schools_teacher(self):
        response = self.admin_client_a.post("/api/teaching-assignments/", {
            "teacher": self.user_b.profile.id, "school_class": self.class_7a.id, "subject": self.maths.id,
        })
        # Another school's record is rejected exactly like one that doesn't exist.
        self.assertEqual(response.status_code, 400)

    # --- students

    def test_teacher_sees_only_students_in_own_classes(self):
        ids = [s["id"] for s in self.client_a.get("/api/students/").data]
        self.assertEqual(ids, [self.mine.id])
        self.assertEqual(self.client_a.get(f"/api/students/{self.not_mine.id}/").status_code, 404)

    def test_admin_sees_all_students(self):
        ids = {s["id"] for s in self.admin_client_a.get("/api/students/").data}
        self.assertEqual(ids, {self.mine.id, self.not_mine.id})

    def test_teacher_with_no_assignments_sees_no_students(self):
        from .models import TeachingAssignment

        TeachingAssignment.objects.all().delete()
        self.assertEqual(self.client_a.get("/api/students/").data, [])

    def test_teacher_can_only_add_students_to_own_classes(self):
        ok = self.client_a.post("/api/students/", {"first_name": "New", "last_name": "Kid",
                                                   "school_class": self.class_7a.id})
        self.assertEqual(ok.status_code, 201)
        other = self.client_a.post("/api/students/", {"first_name": "New", "last_name": "Kid",
                                                      "school_class": self.class_7b.id})
        self.assertEqual(other.status_code, 403)
        none = self.client_a.post("/api/students/", {"first_name": "New", "last_name": "Kid"})
        self.assertEqual(none.status_code, 403)

    def test_teacher_cannot_move_student_to_a_class_they_dont_teach(self):
        response = self.client_a.patch(f"/api/students/{self.mine.id}/", {"school_class": self.class_7b.id})
        self.assertEqual(response.status_code, 403)

    # --- grades

    def test_teacher_sees_all_subjects_for_own_class_only(self):
        ids = {g["id"] for g in self.client_a.get("/api/grades/").data}
        self.assertEqual(ids, {self.art_grade.id})

    def test_teacher_can_grade_own_subject_only(self):
        ok = self.client_a.post("/api/grades/", {"student": self.mine.id, "subject": self.maths.id,
                                                 "term": self.term.id, "score": "70"})
        self.assertEqual(ok.status_code, 201)
        art = self.client_a.post("/api/grades/", {"student": self.mine.id, "subject": self.art.id,
                                                  "term": self.term.id, "score": "70"})
        self.assertEqual(art.status_code, 403)

    def test_teacher_cannot_change_or_delete_another_subjects_grade(self):
        self.assertEqual(self.client_a.patch(f"/api/grades/{self.art_grade.id}/", {"score": "99"}).status_code, 403)
        self.assertEqual(self.client_a.delete(f"/api/grades/{self.art_grade.id}/").status_code, 403)

    def test_teacher_cannot_move_a_grade_into_a_subject_they_dont_teach(self):
        grade = self.client_a.post("/api/grades/", {"student": self.mine.id, "subject": self.maths.id,
                                                    "term": self.term.id, "score": "70"}).data
        response = self.client_a.patch(f"/api/grades/{grade['id']}/", {"subject": self.art.id})
        self.assertEqual(response.status_code, 403)

    # --- attendance

    def test_teacher_takes_attendance_for_own_class_only(self):
        ok = self.client_a.post("/api/attendance/", {"student": self.mine.id, "date": "2026-09-01",
                                                     "status": "present"})
        self.assertEqual(ok.status_code, 201)
        other = self.client_a.post("/api/attendance/", {"student": self.not_mine.id, "date": "2026-09-01",
                                                        "status": "present"})
        self.assertEqual(other.status_code, 403)

    # --- reports

    def test_teacher_cannot_generate_report_for_another_class(self):
        response = self.client_a.post("/api/reports/generate/", {"student": self.not_mine.id,
                                                                 "term": self.term.id})
        self.assertEqual(response.status_code, 403)

    # --- messaging

    def test_teacher_contacts_are_parents_of_own_students_only(self):
        contacts = {c["id"] for c in self.client_a.get("/api/conversations/contacts/").data}
        self.assertEqual(contacts, {self.my_parent.id})
        admin_contacts = {c["id"] for c in self.admin_client_a.get("/api/conversations/contacts/").data}
        self.assertEqual(admin_contacts, {self.my_parent.id, self.other_parent.id})

    def test_teacher_cannot_message_parents_of_other_classes(self):
        response = self.client_a.post("/api/conversations/", {
            "participant_ids": [self.other_parent.id], "body": "Hello",
        }, format="json")
        self.assertEqual(response.status_code, 400)


class InviteRenewalAndAdminResetTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)

    def test_admin_renews_an_expired_invite_with_a_new_link(self):
        from django.utils import timezone

        invite = Invite.objects.create(school=self.school_a, email="late@alpha.test", name="Late",
                                       invited_by=self.admin_a)
        invite.expires_at = timezone.now() - timezone.timedelta(days=1)
        invite.save()
        old_token = invite.token

        response = self.admin_client_a.post(f"/api/invites/{invite.id}/renew/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "pending")
        invite.refresh_from_db()
        self.assertNotEqual(invite.token, old_token)
        self.assertGreater(invite.expires_at, timezone.now() + timezone.timedelta(days=6))
        # The old link no longer works; the new one does.
        self.assertEqual(self.client.get(f"/api/invites/preview/{old_token}/").status_code, 404)
        accept = self.client.post("/api/invites/accept/", {"token": invite.token, "password": "a-long-Password-123"})
        self.assertEqual(accept.status_code, 201)
        self.assertTrue(ActivityLog.objects.filter(action="staff_invite.renewed").exists())

    def test_accepted_invite_cannot_be_renewed(self):
        from django.utils import timezone

        invite = Invite.objects.create(school=self.school_a, email="x@alpha.test", name="X",
                                       invited_by=self.admin_a, accepted_at=timezone.now())
        self.assertEqual(self.admin_client_a.post(f"/api/invites/{invite.id}/renew/").status_code, 400)

    def test_teacher_and_other_school_cannot_renew(self):
        invite = Invite.objects.create(school=self.school_a, email="y@alpha.test", name="Y", invited_by=self.admin_a)
        self.assertEqual(self.client_a.post(f"/api/invites/{invite.id}/renew/").status_code, 403)
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.post(f"/api/invites/{invite.id}/renew/").status_code, 404)

    def test_admin_sends_a_staff_member_a_password_reset_email(self):
        response = self.admin_client_a.post(f"/api/staff/{self.user_a.profile.id}/send-password-reset/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["teacher.a@alpha.test"])
        self.assertTrue(PasswordResetToken.objects.filter(user=self.user_a).exists())
        self.assertTrue(ActivityLog.objects.filter(action="password.reset_sent").exists())

    def test_teacher_cannot_send_resets_and_deactivated_accounts_are_refused(self):
        self.assertEqual(
            self.client_a.post(f"/api/staff/{self.admin_a.profile.id}/send-password-reset/").status_code, 403
        )
        self.admin_client_a.post(f"/api/staff/{self.user_a.profile.id}/deactivate/")
        response = self.admin_client_a.post(f"/api/staff/{self.user_a.profile.id}/send-password-reset/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_cannot_send_reset_to_another_schools_staff(self):
        response = self.admin_client_a.post(f"/api/staff/{self.user_b.profile.id}/send-password-reset/")
        self.assertEqual(response.status_code, 404)


class WholeClassAssignmentTests(SchoolScopedAPITestCase):
    """An assignment with no subject lets a teacher grade every subject in that class."""

    def setUp(self):
        super().setUp()
        from gradebook.models import Subject, Term
        from students.models import SchoolClass, Student, YearGroup

        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 3")
        self.class_3a = SchoolClass.objects.create(year_group=year, name="3A")
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")
        self.art = Subject.objects.create(school=self.school_a, name="Art")
        self.term = Term.objects.create(school=self.school_a, name="Term 1")
        self.student = Student.objects.create(school=self.school_a, first_name="Ivy", last_name="Three",
                                              school_class=self.class_3a)

    def test_admin_assigns_whole_class_and_teacher_grades_any_subject(self):
        response = self.admin_client_a.post("/api/teaching-assignments/", {
            "teacher": self.user_a.profile.id, "school_class": self.class_3a.id,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["subject_name"], "All subjects")
        for subject in (self.maths, self.art):
            grade = self.client_a.post("/api/grades/", {"student": self.student.id, "subject": subject.id,
                                                        "term": self.term.id, "score": "80"})
            self.assertEqual(grade.status_code, 201)

    def test_duplicate_whole_class_assignment_rejected(self):
        body = {"teacher": self.user_a.profile.id, "school_class": self.class_3a.id}
        self.assertEqual(self.admin_client_a.post("/api/teaching-assignments/", body).status_code, 201)
        self.assertEqual(self.admin_client_a.post("/api/teaching-assignments/", body).status_code, 400)


class DashboardTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        from datetime import date

        from attendance.models import AttendanceRecord
        from gradebook.models import Term
        from guardians.models import Guardian
        from reporting.models import StudentReport
        from students.models import SchoolClass, Student, YearGroup

        self.admin_client_a = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        c7a = SchoolClass.objects.create(year_group=year, name="7A")
        SchoolClass.objects.create(year_group=year, name="7B")  # no students: left out
        c7c = SchoolClass.objects.create(year_group=year, name="7C")
        self.ann = Student.objects.create(school=self.school_a, first_name="Ann", last_name="A", school_class=c7a)
        self.ben = Student.objects.create(school=self.school_a, first_name="Ben", last_name="B", school_class=c7a)
        Student.objects.create(school=self.school_a, first_name="Cy", last_name="C", school_class=c7c)
        Student.objects.create(school=self.school_b, first_name="Other", last_name="School")
        AttendanceRecord.objects.create(student=self.ann, date=date.today(), status="present")
        AttendanceRecord.objects.create(student=self.ben, date=date.today(), status="absent")
        parent = User.objects.create_user(username="p@x.test", email="p@x.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a).students.add(self.ann)
        term = Term.objects.create(school=self.school_a, name="T1")
        StudentReport.objects.create(student=self.ann, term=term, progress_summary="s", report_comment="c",
                                     status="submitted")
        Invite.objects.create(school=self.school_a, email="new@a.test", name="New", invited_by=self.admin_a)

    def test_admin_sees_todays_picture(self):
        data = self.admin_client_a.get("/api/dashboard/").data
        att = data["attendance_today"]
        self.assertEqual((att["students"], att["marked"], att["absent"], att["rate"]), (3, 2, 1, 50.0))
        self.assertEqual(att["classes_not_taken"], ["7C"])
        self.assertEqual([c["name"] for c in att["classes"]], ["7A", "7C"])
        self.assertEqual(data["reports_waiting"]["count"], 1)
        self.assertEqual(data["invites"]["pending"], 1)
        without = data["students_without_parent"]
        self.assertEqual((without["count"], without["total_students"]), (2, 3))
        self.assertNotIn("Ann A", [s["name"] for s in without["items"]])

    def test_deactivated_parent_counts_as_no_parent(self):
        User.objects.filter(email="p@x.test").update(is_active=False)
        self.assertEqual(self.admin_client_a.get("/api/dashboard/").data["students_without_parent"]["count"], 3)

    def test_teacher_cannot_see_dashboard(self):
        self.assertEqual(self.client_a.get("/api/dashboard/").status_code, 403)

    def test_only_own_school_is_counted(self):
        self.make_admin(self.user_b)
        data = self.client_b.get("/api/dashboard/").data
        self.assertEqual(data["students_without_parent"]["total_students"], 1)
        self.assertEqual(data["reports_waiting"]["count"], 0)
