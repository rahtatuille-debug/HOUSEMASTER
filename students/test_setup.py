"""New schools: self sign-up and the setup wizard."""
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from unittest.mock import patch

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from gradebook.models import Subject, Term

from .models import School, SchoolClass, YearGroup
from .presets import SYSTEMS

SIGNUP = {"school_name": "Sunrise Academy", "name": "Jane Wanjiru", "email": "Jane@Sunrise.test",
          "password": "a-long-Password-123", "accept_privacy": True}


def finish_payload(**overrides):
    body = {
        "name": "Sunrise Academy", "motto": "Rise and shine", "address": "Box 1, Nakuru", "phone": "+254 700 000 000",
        "email": "office@sunrise.test", "privacy_contact": "privacy@sunrise.test",
        "education_system": "cbc",
        "year_groups": [{"name": "Grade 7", "classes": ["7 East", "7 West"]}, {"name": "Grade 8", "classes": ["Grade 8"]}],
        "subjects": ["English", "Mathematics", "English "],
        "terms": [{"name": "Term 1 2026", "start_date": "2026-01-06", "end_date": "2026-04-03"},
                  {"name": "Term 2 2026", "start_date": "2026-04-28", "end_date": "2026-08-01"}],
        "grading_scale": "cbc8", "report_tone": "warm",
    }
    body.update(overrides)
    return body


class RegistrationTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.anon = APIClient()

    def test_sign_up_creates_a_school_and_its_admin_who_must_then_set_up(self):
        response = self.anon.post("/api/schools/register/", SIGNUP)
        self.assertEqual(response.status_code, 201)
        profile = Profile.objects.get(user__email="jane@sunrise.test")
        self.assertEqual((profile.role, profile.school.name, profile.display_name),
                         ("admin", "Sunrise Academy", "Jane Wanjiru"))
        self.assertIsNotNone(profile.privacy_accepted_at)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        school = client.get("/api/me/").data["school"]
        self.assertFalse(school["setup_completed"])

    def test_sign_up_rules(self):
        self.assertEqual(self.anon.post("/api/schools/register/", {**SIGNUP, "accept_privacy": False}).status_code, 400)
        self.assertEqual(self.anon.post("/api/schools/register/", {**SIGNUP, "password": "123"}).status_code, 400)
        taken = self.anon.post("/api/schools/register/", {**SIGNUP, "email": "teacher.a@alpha.test"})
        self.assertEqual(taken.status_code, 400)
        self.assertFalse(School.objects.filter(name="Sunrise Academy").exists())

    def test_sign_ups_are_rate_limited(self):
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"school_registration": "2/hour"}):
            codes = [self.anon.post("/api/schools/register/", {**SIGNUP, "email": f"a{i}@sunrise.test"}).status_code
                     for i in range(3)]
        self.assertEqual(codes, [201, 201, 429])


class SetupWizardTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)

    def test_state_lists_every_system_and_what_exists(self):
        YearGroup.objects.create(school=self.school_a, name="Grade 7")
        data = self.admin.get("/api/setup/").data
        self.assertEqual([s["key"] for s in data["systems"]], list(SYSTEMS))
        cbc = data["systems"][0]
        self.assertIn("Junior school", [s["name"] for s in cbc["stages"]])
        self.assertEqual(len(cbc["terms"]), 3)
        self.assertIn("kcse", [s["key"] for s in data["scales"]])
        self.assertEqual(data["existing"]["year_groups"], ["Grade 7"])

    def test_progress_is_saved_for_later(self):
        self.admin.patch("/api/setup/", {"progress": {"step": 3, "education_system": "british"}}, format="json")
        self.assertEqual(self.admin.get("/api/setup/").data["school"]["setup_progress"]["step"], 3)
        self.assertEqual(self.admin.patch("/api/setup/", {"progress": "nope"}, format="json").status_code, 400)

    def test_finishing_creates_everything_and_opens_the_school(self):
        response = self.admin.post("/api/setup/finish/", finish_payload(), format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], {"year_groups": 2, "classes": 3, "subjects": 2, "terms": 2, "assessment_types": 0})
        self.school_a.refresh_from_db()
        self.assertEqual((self.school_a.education_system, self.school_a.grading_scale, self.school_a.motto),
                         ("cbc", "cbc8", "Rise and shine"))
        # The structure is done; the school opens once its people are added.
        self.assertIsNotNone(self.school_a.structure_completed_at)
        self.assertIsNone(self.school_a.setup_completed_at)
        self.assertEqual(set(SchoolClass.objects.filter(year_group__school=self.school_a).values_list("name", flat=True)),
                         {"7 East", "7 West", "Grade 8"})
        self.assertEqual(Term.objects.get(school=self.school_a, name="Term 2 2026").start_date.isoformat(), "2026-04-28")
        school = self.admin.get("/api/me/").data["school"]
        self.assertEqual((school["setup_completed"], school["setup_stage"]), (False, "people"))
        self.assertTrue(ActivityLog.objects.filter(action="school.setup_finished").exists())

    def test_finishing_twice_does_not_duplicate(self):
        self.admin.post("/api/setup/finish/", finish_payload(), format="json")
        again = self.admin.post("/api/setup/finish/", finish_payload(subjects=["English", "Kiswahili"]), format="json")
        self.assertEqual(again.data["created"], {"year_groups": 0, "classes": 0, "subjects": 1, "terms": 0, "assessment_types": 0})
        self.assertEqual(Subject.objects.filter(school=self.school_a, name="English").count(), 1)

    def test_bad_choices_are_rejected(self):
        for bad in (
            {"education_system": "martian"},
            {"grading_scale": "stars"},
            {"year_groups": []},
            {"year_groups": [{"name": "Grade 7", "classes": []}]},
            {"year_groups": [{"name": "Grade 7", "classes": ["A", "a"]}]},
            {"subjects": [" "]},
            {"terms": [{"name": "T1", "start_date": "2026-05-01", "end_date": "2026-01-01"}]},
        ):
            self.assertEqual(self.admin.post("/api/setup/finish/", finish_payload(**bad), format="json").status_code,
                             400, bad)
        self.assertFalse(YearGroup.objects.filter(school=self.school_a).exists())

    def test_only_admins_and_only_their_own_school(self):
        self.assertEqual(self.client_a.get("/api/setup/").status_code, 403)
        self.assertEqual(self.client_a.post("/api/setup/finish/", finish_payload(), format="json").status_code, 403)
        self.admin.post("/api/setup/finish/", finish_payload(), format="json")
        self.assertFalse(YearGroup.objects.filter(school=self.school_b).exists())

    def test_every_preset_can_be_finished(self):
        from .presets import suggested_terms
        for key, system in SYSTEMS.items():
            stage = system["stages"][-1]
            body = finish_payload(
                education_system=key, grading_scale=system["scales"][0], subjects=stage["subjects"],
                year_groups=[{"name": yg, "classes": [yg]} for yg in stage["year_groups"]],
                terms=suggested_terms(key),
            )
            response = self.admin.post("/api/setup/finish/", body, format="json")
            self.assertEqual(response.status_code, 200, (key, response.data))
