"""
One login, several schools (accounts/memberships.py): joining a second school with the same email and password,
switching between schools, a teacher who is also a parent, and each school deactivating or erasing only its own
part of the account.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient

from guardians.models import Guardian, GuardianInvite
from messaging.models import Conversation, ConversationParticipant
from students.models import Student

from .models import Invite, Profile
from .tests import SchoolScopedAPITestCase

PASSWORD = "pass1234"


def bearer(tokens):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


class MembershipTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.amina = Student.objects.create(school=self.school_a, first_name="Amina", last_name="K")
        self.baraka = Student.objects.create(school=self.school_b, first_name="Baraka", last_name="O")
        self.admin_b = User.objects.create_user(username="admin_b", email="admin.b@beta.test", password=PASSWORD)
        Profile.objects.create(user=self.admin_b, school=self.school_b, role=Profile.Role.ADMIN)

    def login(self, email="teacher.a@alpha.test", password=PASSWORD):
        cache.clear()
        return APIClient().post("/api/token/", {"email": email, "password": password}, format="json")

    def join_beta(self, password=PASSWORD):
        """Beta invites Alpha's teacher, who accepts with the password they already have."""
        invite = Invite.objects.create(school=self.school_b, email="Teacher.A@alpha.test", name="Teacher A",
                                       role="teacher", invited_by=self.admin_b)
        preview = APIClient().get(f"/api/invites/preview/{invite.token}/")
        self.assertTrue(preview.data["has_account"])
        return APIClient().post("/api/invites/accept/", {"token": invite.token, "password": password,
                                                          "accept_privacy": True}, format="json")

    def students(self, client):
        data = client.get("/api/students/").data
        return {s["first_name"] for s in (data["results"] if isinstance(data, dict) else data)}

    def test_joining_a_second_school_keeps_one_login(self):
        response = self.join_beta()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.filter(email__iexact="teacher.a@alpha.test").count(), 1)
        beta = bearer(response.data)
        me = beta.get("/api/me/").data
        self.assertEqual(me["school"]["name"], "Beta College")
        self.assertEqual(sorted(m["school"] for m in me["memberships"]), ["Alpha Academy", "Beta College"])
        self.assertEqual([m["school"] for m in me["memberships"] if m["current"]], ["Beta College"])

    def test_the_wrong_password_joins_nothing(self):
        response = self.join_beta(password="not-my-password")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)
        self.assertFalse(Profile.objects.filter(user=self.user_a, school=self.school_b).exists())

    def test_each_session_sees_only_its_own_school(self):
        self.join_beta()
        self.make_admin(self.user_a)  # admin at Alpha, teacher at Beta
        alpha = bearer(self.login().data)  # signs in where they were last: Beta (just joined)
        self.assertEqual(alpha.get("/api/me/").data["school"]["name"], "Beta College")
        key = next(m["key"] for m in alpha.get("/api/account/memberships/").data if m["school"] == "Alpha Academy")
        alpha = bearer(alpha.post("/api/account/switch/", {"membership": key}, format="json").data)
        self.assertEqual(alpha.get("/api/me/").data["role"], "admin")
        self.assertEqual(self.students(alpha), {"Amina"})
        beta_key = next(m["key"] for m in alpha.get("/api/account/memberships/").data if m["school"] == "Beta College")
        beta = bearer(alpha.post("/api/account/switch/", {"membership": beta_key}, format="json").data)
        self.assertEqual(beta.get("/api/me/").data["role"], "teacher")
        self.assertNotIn("Amina", self.students(beta))

    def test_switching_to_someone_elses_membership_is_refused(self):
        other = Profile.objects.get(user=self.admin_b)
        response = self.client_a.post("/api/account/switch/", {"membership": f"staff:{other.pk}"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_a_teacher_can_be_a_parent_at_their_own_school(self):
        parent = Guardian.objects.create(user=self.user_a, school=self.school_a, display_name="Teacher A")
        parent.students.add(self.amina)
        staff = self.client_a
        self.assertEqual(staff.get("/api/guardian-me/").status_code, 403)  # this session is staff
        as_parent = bearer(staff.post("/api/account/switch/", {"membership": f"parent:{parent.pk}"},
                                      format="json").data)
        self.assertEqual(as_parent.get("/api/me/").status_code, 403)
        self.assertEqual(as_parent.get("/api/students/").status_code, 403)
        self.assertEqual(as_parent.get("/api/guardian-me/").data["name"], "Teacher A")

    def test_each_school_deactivates_only_its_own_part(self):
        beta = bearer(self.join_beta().data)
        alpha_profile = Profile.objects.get(user=self.user_a, school=self.school_a)
        self.assertEqual(self.authed_client(self.admin_a).post(f"/api/staff/{alpha_profile.pk}/deactivate/")
                         .status_code, 200)
        self.assertEqual(beta.get("/api/me/").status_code, 200)  # Beta untouched
        self.user_a.refresh_from_db()
        self.assertTrue(self.user_a.is_active)
        login = self.login()
        self.assertEqual(login.status_code, 200)
        me = bearer(login.data).get("/api/me/").data
        self.assertEqual(me["school"]["name"], "Beta College")
        self.assertEqual([m["school"] for m in me["memberships"]], ["Beta College"])

    def test_a_session_at_a_school_that_deactivated_them_ends(self):
        self.join_beta()
        alpha_profile = Profile.objects.get(user=self.user_a, school=self.school_a)
        alpha = bearer(self.client_a.post("/api/account/switch/", {"membership": f"staff:{alpha_profile.pk}"},
                                          format="json").data)
        self.authed_client(self.admin_a).post(f"/api/staff/{alpha_profile.pk}/deactivate/")
        self.assertEqual(alpha.get("/api/me/").status_code, 401)

    def test_deactivated_everywhere_closes_the_login(self):
        profile = self.user_a.profile
        self.authed_client(self.admin_a).post(f"/api/staff/{profile.pk}/deactivate/")
        self.assertEqual(self.login().status_code, 401)

    def test_messages_stay_with_their_school(self):
        self.join_beta()
        conversation = Conversation.objects.create(school=self.school_a, kind=Conversation.Kind.DIRECT)
        ConversationParticipant.objects.create(conversation=conversation, user=self.user_a)
        ConversationParticipant.objects.create(conversation=conversation, user=self.admin_a)
        beta_profile = Profile.objects.get(user=self.user_a, school=self.school_b)
        beta = bearer(self.client_a.post("/api/account/switch/", {"membership": f"staff:{beta_profile.pk}"},
                                         format="json").data)
        data = beta.get("/api/conversations/").data
        rows = data["results"] if isinstance(data, dict) else data
        self.assertEqual(rows, [])

    def test_erasing_a_family_at_one_school_keeps_their_login_elsewhere(self):
        from students.privacy import remove_personal_data

        parent = User.objects.create_user(username="pat", email="pat@p.test", password=PASSWORD)
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)
        Guardian.objects.create(user=parent, school=self.school_b, display_name="Pat").students.add(self.baraka)
        remove_personal_data(self.amina, self.admin_a)
        self.assertTrue(User.objects.filter(pk=parent.pk).exists())
        self.assertEqual(list(Guardian.objects.filter(user=parent).values_list("school__name", flat=True)),
                         ["Beta College"])

    def test_a_parent_at_another_school_accepts_with_their_password(self):
        parent = User.objects.create_user(username="pat", email="pat@p.test", password=PASSWORD)
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)
        invite = GuardianInvite.objects.create(school=self.school_b, email="pat@p.test", name="Pat",
                                               invited_by=self.admin_b)
        invite.students.add(self.baraka)
        response = APIClient().post("/api/guardian-invites/accept/", {"token": invite.token, "password": PASSWORD,
                                                                     "accept_privacy": True}, format="json")
        self.assertEqual(response.status_code, 201)
        me = bearer(response.data).get("/api/guardian-me/").data
        self.assertEqual(len(me["memberships"]), 2)
        children = bearer(response.data).get("/api/guardian-students/").data
        rows = children["results"] if isinstance(children, dict) else children
        self.assertEqual([c["first_name"] for c in rows], ["Baraka"])

    def test_registering_another_school_on_the_same_login(self):
        cache.clear()
        response = APIClient().post("/api/schools/register/", {
            "school_name": "Gamma School", "name": "Teacher A", "email": "teacher.a@alpha.test",
            "password": PASSWORD, "accept_privacy": True}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Profile.objects.filter(user=self.user_a).count(), 2)
        me = bearer(response.data).get("/api/me/").data
        self.assertEqual((me["school"]["name"], me["role"]), ("Gamma School", "admin"))
        wrong = APIClient().post("/api/schools/register/", {
            "school_name": "Delta School", "name": "Teacher A", "email": "teacher.a@alpha.test",
            "password": "wrong-password-1", "accept_privacy": True}, format="json")
        self.assertEqual(wrong.status_code, 400)
