"""
Admissions: a family applies through the school's public link (no
account); admins move the application through the stages, the family is
emailed at each decision, and enrolling makes a student and invites the parent.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.tests import SchoolScopedAPITestCase
from guardians.models import Guardian, GuardianInvite
from students.models import School, SchoolClass, Student, YearGroup

from .models import AdmissionsSettings, Application


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class AdmissionsTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        self.y7 = YearGroup.objects.create(school=self.school_a, name="Year 7", order=0)
        self.y8 = YearGroup.objects.create(school=self.school_a, name="Year 8", order=1)
        self.c7a = SchoolClass.objects.create(year_group=self.y7, name="7A")
        self.settings = AdmissionsSettings.objects.create(school=self.school_a, is_open=True, intro="Welcome!")
        self.public = APIClient()
        self.url = f"/api/admissions/apply/{self.settings.token}/"

    def form(self, **extra):
        return {"year_group": self.y7.id, "first_name": "Zara", "last_name": "Patel", "date_of_birth": "2015-03-02",
                "gender": "female", "current_school": "Hill Primary", "mode_of_learning": "day",
                "parent_name": "Priya Patel", "parent_email": "priya@example.test", "parent_phone": "+254 700 000 001",
                "relationship": "mother", "consent": True, **extra}

    def apply(self, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return self.public.post(self.url, self.form(**extra), format="json")

    def application(self):
        return Application.objects.get(first_name="Zara")

    # --- the public form

    def test_the_form_shows_the_school_and_year_groups(self):
        data = self.public.get(self.url).data
        self.assertEqual((data["school"]["name"], data["intro"]), ("Alpha Academy", "Welcome!"))
        self.assertEqual([y["name"] for y in data["year_groups"]], ["Year 7", "Year 8"])
        self.settings.year_groups.set([self.y8])
        self.assertEqual([y["name"] for y in self.public.get(self.url).data["year_groups"]], ["Year 8"])

    def test_a_family_applies_and_gets_a_reference(self):
        response = self.apply()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["reference"].startswith("A"))
        app = self.application()
        self.assertEqual((app.status, app.school, app.year_group), ("new", self.school_a, self.y7))
        self.assertEqual([m.to for m in mail.outbox], [["priya@example.test"]])
        self.assertIn(response.data["reference"], mail.outbox[0].body)

    def test_closed_or_wrong_links_are_refused(self):
        self.assertEqual(self.public.get("/api/admissions/apply/nope/").status_code, 404)
        self.settings.is_open = False
        self.settings.save()
        self.assertEqual(self.public.get(self.url).status_code, 404)
        self.assertEqual(self.apply().status_code, 404)

    def test_the_form_checks_what_it_needs(self):
        self.assertEqual(self.apply(consent=False).status_code, 400)
        self.assertEqual(self.apply(date_of_birth=None).status_code, 400)
        self.assertEqual(self.apply(mode_of_learning="boarding").status_code, 400)  # no boarding here
        other_school_year = YearGroup.objects.create(school=self.school_b, name="Year 7")
        self.assertEqual(self.apply(year_group=other_school_year.id).status_code, 400)
        self.assertFalse(Application.objects.exists())

    def test_bots_filling_the_hidden_field_are_quietly_ignored(self):
        self.assertEqual(self.apply(website="http://spam").status_code, 201)
        self.assertFalse(Application.objects.exists())

    def test_too_many_applications_from_one_place(self):
        from unittest.mock import patch

        from .views import ApplyThrottle

        cache.clear()
        with patch.dict(ApplyThrottle.THROTTLE_RATES, {"admissions_apply": "2/hour"}):
            codes = [self.apply(first_name=f"K{n}").status_code for n in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    # --- staff

    def test_admins_move_applications_on_and_the_family_is_told(self):
        self.apply()
        app = self.application()
        mail.outbox.clear()
        when = (timezone.now() + timedelta(days=3)).isoformat()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.admin.patch(f"/api/admissions/applications/{app.id}/",
                                        {"status": "interview", "interview_at": when,
                                         "decision_note": "Please bring her last report."}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status_label"], "Interview or test")
        self.assertIn("Please bring her last report.", mail.outbox[0].body)
        with self.captureOnCommitCallbacks(execute=True):
            self.admin.patch(f"/api/admissions/applications/{app.id}/", {"staff_notes": "Strong in maths."},
                             format="json")
        self.assertEqual(len(mail.outbox), 1)  # notes alone send nothing
        with self.captureOnCommitCallbacks(execute=True):
            self.admin.patch(f"/api/admissions/applications/{app.id}/", {"status": "offered"}, format="json")
        self.assertIn("offer Zara a place", mail.outbox[1].body)

    def test_staff_notes_are_never_sent(self):
        self.apply()
        app = self.application()
        with self.captureOnCommitCallbacks(execute=True):
            self.admin.patch(f"/api/admissions/applications/{app.id}/",
                             {"status": "declined", "staff_notes": "Weak interview"}, format="json")
        self.assertNotIn("Weak interview", mail.outbox[-1].body)

    def test_enrolling_makes_a_student_and_invites_the_parent(self):
        self.apply()
        app = self.application()
        self.assertEqual(self.admin.post(f"/api/admissions/applications/{app.id}/enrol/",
                                         {"school_class": self.c7a.id}, format="json").status_code, 400)  # not offered
        self.admin.patch(f"/api/admissions/applications/{app.id}/", {"status": "offered"}, format="json")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.admin.post(f"/api/admissions/applications/{app.id}/enrol/", {"school_class": self.c7a.id},
                                       format="json")
        self.assertEqual(response.status_code, 200, response.data)
        student = Student.objects.get(pk=response.data["student"])
        self.assertEqual((student.first_name, student.school_class, student.gender), ("Zara", self.c7a, "female"))
        invite = GuardianInvite.objects.get(email="priya@example.test")
        self.assertEqual(list(invite.students.all()), [student])
        self.assertEqual(self.application().status, "enrolled")
        self.assertEqual(self.admin.post(f"/api/admissions/applications/{app.id}/enrol/",
                                         {"school_class": self.c7a.id}, format="json").status_code, 400)
        self.assertEqual(self.admin.patch(f"/api/admissions/applications/{app.id}/", {"status": "new"},
                                          format="json").status_code, 400)

    def test_enrolling_adds_the_child_to_an_existing_parent_account(self):
        user = User.objects.create_user(username="priya@example.test", email="priya@example.test", password="x")
        parent = Guardian.objects.create(user=user, school=self.school_a, display_name="Priya")
        self.apply(status="offered")
        app = self.application()
        Application.objects.filter(pk=app.pk).update(status="accepted")
        response = self.admin.post(f"/api/admissions/applications/{app.id}/enrol/", {"school_class": self.c7a.id},
                                   format="json")
        self.assertIn("Added Zara Patel to Priya's parent account", response.data["message"])
        self.assertEqual(parent.students.count(), 1)

    def test_list_filters_and_counts(self):
        self.apply()
        self.apply(first_name="Omar", parent_email="o@example.test")
        Application.objects.filter(first_name="Omar").update(status="offered")
        self.assertEqual(len(self.admin.get("/api/admissions/applications/", {"status": "offered"}).data), 1)
        self.assertEqual(len(self.admin.get("/api/admissions/applications/", {"q": "zara"}).data), 1)
        self.assertEqual(self.admin.get("/api/admissions/applications/summary/").data["counts"],
                         {"new": 1, "offered": 1})

    def test_settings_open_close_and_new_link(self):
        settings = self.admin.patch("/api/admissions/settings/", {"is_open": False, "year_groups": [self.y7.id]},
                                    format="json").data
        self.assertEqual((settings["is_open"], settings["year_groups"]), (False, [self.y7.id]))
        old = settings["link_token"]
        new = self.admin.post("/api/admissions/settings/", {"new_link": True}, format="json").data["link_token"]
        self.assertNotEqual(old, new)

    def test_only_admins_of_the_school(self):
        self.apply()
        app = self.application()
        self.assertEqual(self.client_a.get("/api/admissions/applications/").status_code, 403)  # a teacher
        self.make_admin(self.user_b)
        self.assertEqual(self.client_b.get("/api/admissions/applications/").data, [])
        self.assertEqual(self.client_b.get(f"/api/admissions/applications/{app.id}/").status_code, 404)
        self.assertEqual(self.public.get("/api/admissions/applications/").status_code, 401)

    def test_boarding_schools_take_boarding_applications(self):
        School.objects.filter(pk=self.school_a.pk).update(has_boarding=True)
        self.assertEqual(self.apply(mode_of_learning="boarding").status_code, 201)
        self.assertTrue(self.public.get(self.url).data["school"]["has_boarding"])


class AdmissionsDemoTests(SchoolScopedAPITestCase):
    def test_demo(self):
        from .demo import STAGES, fill_demo

        YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.assertEqual(fill_demo(self.school_a, "alpha.test"), len(STAGES))
        self.assertTrue(AdmissionsSettings.objects.get(school=self.school_a).is_open)
        self.assertEqual(Application.objects.filter(status="new").count(), 4)
