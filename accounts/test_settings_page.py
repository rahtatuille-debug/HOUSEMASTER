from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Profile
from activity.models import ActivityLog as ActivityEntry
from guardians.models import Guardian
from students.models import School

User = get_user_model()
PASSWORD = "Old-Password-123"


def staff(school, email, role=Profile.Role.TEACHER):
    user = User.objects.create_user(username=email, email=email, password=PASSWORD)
    Profile.objects.create(user=user, school=school, role=role, display_name=email.split("@")[0].title())
    return user


def signed_in(user):
    client = APIClient()
    tokens = client.post("/api/token/", {"email": user.email, "password": PASSWORD}, format="json").json()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client, tokens


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class OwnDetailsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(name="Alpha")
        self.other_school = School.objects.create(name="Beta")
        self.teacher = staff(self.school, "tom@alpha.example")
        self.admin = staff(self.school, "amina@alpha.example", Profile.Role.ADMIN)
        self.outsider = staff(self.other_school, "bob@beta.example", Profile.Role.ADMIN)

    def test_staff_keep_their_own_details(self):
        client, _ = signed_in(self.teacher)
        res = client.patch("/api/me/", {"title": "Mr", "phone": "+254 712 345 678", "emergency_contact_name": "  Jane   Doe ",
                                         "emergency_contact_phone": "+254 722 000 111", "email_notifications": False}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual((body["title"], body["phone"], body["emergency_contact_name"]), ("Mr", "+254 712 345 678", "Jane Doe"))
        self.assertNotIn("email", body)
        self.assertFalse(body["email_notifications"])
        self.assertEqual(body["name"], "Tom")  # no name sent: unchanged
        entry = ActivityEntry.objects.get(action="staff.details_changed")
        self.assertNotIn("712", str(entry.summary) + str(entry.details))  # which fields, never their values

    def test_bad_phone_and_title_are_refused(self):
        client, _ = signed_in(self.teacher)
        self.assertEqual(client.patch("/api/me/", {"phone": "call me"}, format="json").status_code, 400)
        self.assertEqual(client.patch("/api/me/", {"title": "Lord"}, format="json").status_code, 400)
        self.assertEqual(client.patch("/api/me/", {"name": ""}, format="json").status_code, 400)

    def test_role_cannot_be_changed_through_me(self):
        client, _ = signed_in(self.teacher)
        client.patch("/api/me/", {"role": "admin", "phone": "+254 712 345 678"}, format="json")
        self.assertEqual(Profile.objects.get(user=self.teacher).role, Profile.Role.TEACHER)

    def test_only_their_own_schools_admins_see_the_details(self):
        Profile.objects.filter(user=self.teacher).update(phone="+254 712 345 678", emergency_contact_name="Jane")
        admin, _ = signed_in(self.admin)
        rows = {r["email"]: r for r in admin.get("/api/staff/").json()["results"]} if isinstance(
            admin.get("/api/staff/").json(), dict) else {r["email"]: r for r in admin.get("/api/staff/").json()}
        self.assertEqual(rows["tom@alpha.example"]["phone"], "+254 712 345 678")
        outsider, _ = signed_in(self.outsider)
        listing = outsider.get("/api/staff/").json()
        listing = listing["results"] if isinstance(listing, dict) else listing
        self.assertNotIn("tom@alpha.example", [r["email"] for r in listing])
        teacher, _ = signed_in(self.teacher)
        self.assertEqual(teacher.get("/api/staff/").status_code, 403)
        # And an admin can't overwrite them.
        tom = Profile.objects.get(user=self.teacher)
        admin.patch(f"/api/staff/{tom.pk}/", {"phone": "+44 7700 900123"}, format="json")
        tom.refresh_from_db()
        self.assertEqual(tom.phone, "+254 712 345 678")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class PasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(name="Alpha")
        self.teacher = staff(self.school, "tom@alpha-school.org")  # a deliverable address, so the notice is sent

    def test_change_password_signs_out_other_devices_but_not_this_one(self):
        phone, _ = signed_in(self.teacher)
        laptop, _ = signed_in(self.teacher)
        with self.captureOnCommitCallbacks(execute=True):
            res = laptop.post("/api/me/password/", {"current_password": PASSWORD, "new_password": "A-much-better-pass-42"},
                              format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(phone.get("/api/me/").status_code, 401)
        laptop.credentials(HTTP_AUTHORIZATION=f"Bearer {res.json()['access']}")
        self.assertEqual(laptop.get("/api/me/").status_code, 200)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password("A-much-better-pass-42"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("A-much-better-pass-42", mail.outbox[0].body)
        self.assertTrue(ActivityEntry.objects.filter(action="account.password_changed").exists())

    def test_wrong_current_or_weak_new_password_is_refused(self):
        client, _ = signed_in(self.teacher)
        res = client.post("/api/me/password/", {"current_password": "nope", "new_password": "A-much-better-pass-42"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("current_password", res.json())
        res = client.post("/api/me/password/", {"current_password": PASSWORD, "new_password": "123"}, format="json")
        self.assertIn("new_password", res.json())
        res = client.post("/api/me/password/", {"current_password": PASSWORD, "new_password": PASSWORD}, format="json")
        self.assertIn("new_password", res.json())
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password(PASSWORD))

    @override_settings(REST_FRAMEWORK={
        **__import__("django.conf").conf.settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**__import__("django.conf").conf.settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
                                   "password_change_user": "3/hour"},
    })
    def test_guessing_is_limited(self):
        from accounts.throttles import PasswordChangeUserThrottle
        PasswordChangeUserThrottle.THROTTLE_RATES = {"password_change_user": "3/hour"}
        try:
            client, _ = signed_in(self.teacher)
            codes = [client.post("/api/me/password/", {"current_password": f"guess{i}", "new_password": "x"},
                                 format="json").status_code for i in range(5)]
            self.assertEqual(codes[-1], 429)
        finally:
            from django.conf import settings
            PasswordChangeUserThrottle.THROTTLE_RATES = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]

    def test_parents_can_change_theirs_too(self):
        user = User.objects.create_user(username="grace@x.example", email="grace@x.example", password=PASSWORD)
        Guardian.objects.create(user=user, school=self.school, display_name="Grace")
        client, _ = signed_in(user)
        res = client.post("/api/me/password/", {"current_password": PASSWORD, "new_password": "A-much-better-pass-42"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)

    def test_sign_out_other_devices(self):
        phone, _ = signed_in(self.teacher)
        laptop, _ = signed_in(self.teacher)
        res = laptop.post("/api/me/sign-out-others/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(phone.get("/api/me/").status_code, 401)
        laptop.credentials(HTTP_AUTHORIZATION=f"Bearer {res.json()['access']}")
        self.assertEqual(laptop.get("/api/me/").status_code, 200)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.check_password(PASSWORD))


class RoutineEmailChoiceTests(TestCase):
    def test_a_class_teacher_who_turned_routine_emails_off_isnt_sent_absence_reports(self):
        from absences.services import class_teacher_emails
        from accounts.models import StaffRole
        from students.models import SchoolClass, Student, YearGroup

        school = School.objects.create(name="Alpha")
        year = YearGroup.objects.create(school=school, name="Year 7")
        klass = SchoolClass.objects.create(name="7A", year_group=year)
        student = Student.objects.create(school=school, first_name="Amina", last_name="K", school_class=klass)
        on, off = staff(school, "on@alpha.example"), staff(school, "off@alpha.example")
        for user in (on, off):
            StaffRole.objects.create(profile=user.profile, role=StaffRole.Role.CLASS_TEACHER, school_class=klass)
        Profile.objects.filter(user=off).update(email_notifications=False)
        self.assertEqual(class_teacher_emails(student), ["on@alpha.example"])
