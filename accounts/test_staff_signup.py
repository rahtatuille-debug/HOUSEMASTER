"""The staff sign-up link: one link for all new staff; admins approve; approved people get the usual invite."""
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import Invite, Profile, StaffJoinLink, StaffSignupRequest
from accounts.tests import SchoolScopedAPITestCase


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class StaffSignupTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # sign-up throttling
        self.admin = self.authed_client(self.admin_a)
        self.public = APIClient()

    def link(self, action="create", client=None):
        return (client or self.admin).post("/api/staff-join-link/", {"action": action}, format="json").data["token"]

    def join(self, token, **overrides):
        body = {"name": "Grace  Wanjiru", "email": "grace@school-a.org", "phone": "+254 700 000 001",
                "note": "I teach Year 8 Maths", "accept_privacy": True}
        body.update(overrides)
        return self.public.post(f"/api/staff-join/{token}/", body, format="json")

    def decide(self, decision, *requests, client=None):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.admin).post("/api/staff-signup-requests/",
                                               {"ids": [r.id for r in requests], "decision": decision}, format="json")

    def test_someone_signs_up_an_admin_approves_and_they_choose_a_password(self):
        token = self.link()
        self.assertEqual(self.public.get(f"/api/staff-join/{token}/").data["school_name"], self.school_a.name)
        self.assertEqual(self.join(token).status_code, 201)
        signup = StaffSignupRequest.objects.get()
        self.assertEqual((signup.school, signup.name, signup.note), (self.school_a, "Grace Wanjiru", "I teach Year 8 Maths"))
        self.assertFalse(User.objects.filter(email="grace@school-a.org").exists())  # nothing until approved
        self.assertEqual(self.admin.get("/api/dashboard/").data["staff_signups_waiting"], 1)
        self.assertEqual(self.admin.get("/api/staff-join-link/").data["waiting"], 1)

        mail.outbox.clear()
        result = self.decide("approve", signup).data
        self.assertEqual(result["problems"], [])
        invite = Invite.objects.get(email="grace@school-a.org")
        self.assertEqual((invite.school, invite.role, invite.phone), (self.school_a, "teacher", "+254 700 000 001"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"/invite/{invite.token}", mail.outbox[0].body)

        accept = self.public.post("/api/invites/accept/", {"token": invite.token, "password": "A-long-Password-123",
                                                            "accept_privacy": True}, format="json")
        self.assertEqual(accept.status_code, 201, accept.data)
        profile = Profile.objects.get(user__email="grace@school-a.org")
        self.assertEqual((profile.school, profile.role, profile.name, profile.phone),
                         (self.school_a, "teacher", "Grace Wanjiru", "+254 700 000 001"))

    def test_asking_twice_updates_the_request(self):
        token = self.link()
        self.join(token)
        self.join(token, name="Grace W. Wanjiru", email="GRACE@school-a.org")
        self.assertEqual(StaffSignupRequest.objects.get().name, "Grace W. Wanjiru")

    def test_the_answer_never_reveals_whether_an_email_has_an_account(self):
        token = self.link()
        taken = self.join(token, email=self.user_a.email)
        fresh = self.join(token, email="new@school-a.org")
        self.assertEqual(taken.status_code, fresh.status_code)
        self.assertEqual(taken.data["detail"].replace(self.user_a.email, ""), fresh.data["detail"].replace("new@school-a.org", ""))
        # The admin sees it, and approving it doesn't make a second account.
        request = StaffSignupRequest.objects.get(email=self.user_a.email)
        self.assertTrue(next(r for r in self.admin.get("/api/staff-signup-requests/").data if r["id"] == request.id)["has_account"])
        result = self.decide("approve", request).data
        self.assertEqual(len(result["problems"]), 1)
        self.assertFalse(Invite.objects.filter(email=self.user_a.email).exists())

    def test_turning_down_and_turning_off(self):
        token = self.link()
        self.join(token)
        self.decide("reject", StaffSignupRequest.objects.get())
        self.assertEqual(StaffSignupRequest.objects.get().status, "rejected")
        self.assertFalse(Invite.objects.exists())
        self.link("off")
        self.assertEqual(self.public.get(f"/api/staff-join/{token}/").status_code, 404)
        self.assertEqual(self.join(token, email="x@school-a.org").status_code, 404)
        new = self.link("renew")
        self.assertNotEqual(new, token)
        self.assertEqual(self.public.get(f"/api/staff-join/{token}/").status_code, 404)
        self.assertEqual(self.public.get(f"/api/staff-join/{new}/").status_code, 200)

    def test_bad_input_is_refused(self):
        token = self.link()
        self.assertEqual(self.join(token, accept_privacy=False).status_code, 400)
        self.assertEqual(self.join(token, phone="call me").status_code, 400)
        self.assertEqual(self.join(token, email="not-an-email").status_code, 400)
        self.assertEqual(self.public.get("/api/staff-join/made-up-token/").status_code, 404)

    def test_only_admins_and_only_their_own_school(self):
        token = self.link()
        self.join(token)
        teacher = self.authed_client(self.user_a)
        self.assertEqual(teacher.get("/api/staff-join-link/").status_code, 403)
        self.assertEqual(teacher.get("/api/staff-signup-requests/").status_code, 403)
        admin_b = User.objects.create_user(username="admin-b", email="admin@beta.example", password="x-Pass-12345")
        Profile.objects.create(user=admin_b, school=self.school_b, role=Profile.Role.ADMIN)
        other = self.authed_client(admin_b)
        self.assertEqual(other.get("/api/staff-signup-requests/").data, [])
        other_token = self.link(client=other)
        self.assertNotEqual(other_token, token)
        # Another school's admin can't decide this school's requests.
        result = self.decide("approve", StaffSignupRequest.objects.get(school=self.school_a), client=other).data
        self.assertEqual(result["done"], [])
        self.assertFalse(Invite.objects.exists())
        self.assertEqual(StaffJoinLink.objects.count(), 2)

    def test_the_link_never_makes_an_admin(self):
        token = self.link()
        self.join(token, role="admin")
        self.decide("approve", StaffSignupRequest.objects.get())
        self.assertEqual(Invite.objects.get().role, "teacher")
