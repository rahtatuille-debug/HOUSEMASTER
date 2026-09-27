"""Class sign-up links: parents ask to join with an admission number, admins approve, invites are emailed."""
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from students.models import SchoolClass, Student, YearGroup

from .models import ClassSignupLink, Guardian, GuardianInvite, ParentSignupRequest


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class ClassSignupTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # sign-up throttling
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Grade 7")
        self.east = SchoolClass.objects.create(year_group=year, name="7 East")
        self.west = SchoolClass.objects.create(year_group=year, name="7 West")
        self.amina = Student.objects.create(school=self.school_a, school_class=self.east, first_name="Amina",
                                            last_name="Otieno", external_id="ADM/101")
        self.baraka = Student.objects.create(school=self.school_a, school_class=self.west, first_name="Baraka",
                                             last_name="Otieno", external_id="ADM/102")
        # Another school's student with the same admission number.
        other_class = SchoolClass.objects.create(
            year_group=YearGroup.objects.create(school=self.school_b, name="Grade 7"), name="7B")
        self.other = Student.objects.create(school=self.school_b, school_class=other_class, first_name="Zed",
                                            last_name="B", external_id="ADM/101")
        self.public = APIClient()

    def link(self, klass=None, action="create"):
        rows = self.admin.post("/api/signup-links/", {"school_class": (klass or self.east).id, "action": action},
                               format="json").data
        return next(r for r in rows if r["school_class"] == (klass or self.east).id)["token"]

    def join(self, token, **overrides):
        body = {"name": "Grace Otieno", "email": "grace@example.com", "phone": "+254 700 000 001",
                "relationship": "mother", "admission_number": "adm/101", "accept_privacy": True}
        body.update(overrides)
        return self.public.post(f"/api/join/{token}/", body, format="json")

    def decide(self, decision, *requests):
        with self.captureOnCommitCallbacks(execute=True):
            return self.admin.post("/api/signup-requests/", {"ids": [r.id for r in requests], "decision": decision},
                                   format="json")

    def test_a_parent_signs_up_and_an_admin_approves_them(self):
        token = self.link()
        page = self.public.get(f"/api/join/{token}/").data
        self.assertEqual((page["school_name"], page["class_name"]), ("Alpha Academy", "7 East"))
        self.assertEqual(self.join(token).status_code, 201)
        signup = ParentSignupRequest.objects.get()
        self.assertEqual((signup.student, signup.school), (self.amina, self.school_a))  # never the other school's
        self.assertFalse(User.objects.filter(email="grace@example.com").exists())  # nothing until approved

        waiting = self.admin.get("/api/signup-requests/").data
        self.assertEqual(waiting[0]["student"]["name"], "Amina Otieno")
        self.assertTrue(waiting[0]["student"]["in_this_class"])
        self.assertEqual(self.admin.get("/api/dashboard/").data["parent_signups_waiting"], 1)

        mail.outbox.clear()
        result = self.decide("approve", signup).data
        self.assertEqual(result["problems"], [])
        invite = GuardianInvite.objects.get(email="grace@example.com")
        self.assertEqual((list(invite.students.all()), invite.phone, invite.relationship),
                         ([self.amina], "+254 700 000 001", "mother"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"/guardian-invite/{invite.token}", mail.outbox[0].body)

        # Accepting the invite makes the account, with the details they gave.
        accept = self.public.post("/api/guardian-invites/accept/", {
            "token": invite.token, "password": "A-long-Password-123", "accept_privacy": True}, format="json")
        self.assertEqual(accept.status_code, 201, accept.data)
        guardian = Guardian.objects.get(user__email="grace@example.com")
        self.assertEqual((guardian.phone, guardian.relationship, list(guardian.students.all())),
                         ("+254 700 000 001", "mother", [self.amina]))

    def test_the_answer_never_reveals_whether_a_student_exists(self):
        token = self.link()
        found = self.join(token)
        missing = self.join(token, email="x@example.com", admission_number="NOPE/1")
        self.assertEqual(found.status_code, missing.status_code)
        self.assertEqual(found.data["detail"].replace("grace@example.com", ""),
                         missing.data["detail"].replace("x@example.com", ""))
        # The admin sees there's no match, and can't approve it.
        unmatched = ParentSignupRequest.objects.get(admission_number="NOPE/1")
        self.assertIsNone(unmatched.student)
        self.assertEqual(len(self.decide("approve", unmatched).data["problems"]), 1)
        self.assertEqual(self.decide("reject", unmatched).status_code, 200)
        unmatched.refresh_from_db()
        self.assertEqual(unmatched.status, "rejected")

    def test_a_sibling_joins_an_existing_parent_account(self):
        token = self.link()
        self.join(token)
        self.decide("approve", ParentSignupRequest.objects.get())
        invite = GuardianInvite.objects.get()
        self.public.post("/api/guardian-invites/accept/", {
            "token": invite.token, "password": "A-long-Password-123", "accept_privacy": True}, format="json")
        west = self.link(self.west)
        self.join(west, admission_number="ADM/102")
        signup = ParentSignupRequest.objects.get(status="pending")
        self.assertTrue(self.admin.get("/api/signup-requests/").data[0]["has_account"])
        mail.outbox.clear()
        self.decide("approve", signup)
        guardian = Guardian.objects.get(user__email="grace@example.com")
        self.assertEqual(set(guardian.students.all()), {self.amina, self.baraka})
        self.assertIn("Baraka", mail.outbox[0].subject)

    def test_asking_twice_updates_the_request(self):
        token = self.link()
        self.join(token, phone="1")
        self.join(token, phone="2")
        self.assertEqual(list(ParentSignupRequest.objects.values_list("phone", flat=True)), ["2"])

    def test_links_can_be_turned_off_and_replaced(self):
        token = self.link()
        new = self.link(action="renew")
        self.assertNotEqual(token, new)
        self.assertEqual(self.public.get(f"/api/join/{token}/").status_code, 404)
        self.link(action="off")
        self.assertEqual(self.public.get(f"/api/join/{new}/").status_code, 404)
        self.assertEqual(self.join(new).status_code, 404)

    def test_only_this_schools_admins_manage_links_and_requests(self):
        token = self.link()
        self.join(token)
        self.assertEqual(self.client_a.get("/api/signup-requests/").status_code, 403)
        self.assertEqual(self.client_a.post("/api/signup-links/", {"school_class": self.east.id,
                                                                    "action": "create"}).status_code, 403)
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get("/api/signup-requests/").data, [])
        self.assertEqual(self.client_b.post("/api/signup-links/", {"school_class": self.east.id,
                                                                    "action": "create"}).status_code, 404)
        response = self.client_b.post("/api/signup-requests/", {
            "ids": [ParentSignupRequest.objects.get().id], "decision": "approve"}, format="json")
        self.assertEqual(response.data["done"], [])
        self.assertEqual(ParentSignupRequest.objects.get().status, "pending")

    def test_privacy_consent_and_details_are_required(self):
        token = self.link()
        self.assertEqual(self.join(token, accept_privacy=False).status_code, 400)
        self.assertEqual(self.join(token, email="not-an-email").status_code, 400)
        self.assertEqual(self.join(token, admission_number=" ").status_code, 400)
        self.assertFalse(ParentSignupRequest.objects.exists())

    def test_staff_emails_cant_become_parents(self):
        token = self.link()
        self.join(token, email="teacher.a@alpha.test")
        result = self.decide("approve", ParentSignupRequest.objects.get()).data
        self.assertIn("staff account", result["problems"][0])

    def test_manual_invites_are_emailed_too(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.admin.post("/api/guardian-invites/", {"name": "Joy K", "email": "joy@example.com",
                                                       "students": [self.amina.id]}, format="json")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Amina Otieno", mail.outbox[0].body)
        self.assertEqual(ClassSignupLink.objects.count(), 0)
