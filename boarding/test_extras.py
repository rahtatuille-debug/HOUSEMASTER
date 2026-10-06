"""
Owner-approved follow-ups (2026-10-06):
- X-1: putting a boarder in an occupied bed is refused unless the person says to replace whoever is there;
- X-2: a boarder who leaves while in the sick bay is checked out;
- X-3: a boarder can be marked "leave only with admin approval", and every linked parent is told when leave is
  approved and when the boarder is signed out, even with routine emails turned off.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from activity.models import ActivityLog
from guardians.models import Guardian

from .models import Bed, LeaveRequest, SickBayVisit
from .services import release_boarders
from .test_safeguarding import Fixture


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class BedSwapTests(Fixture):
    def test_an_occupied_bed_is_not_silently_taken(self):
        response = self.matron.post(f"/api/boarding/beds/{self.beds[0].id}/", {"student": self.brian.id}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Amina K", str(response.data))
        self.beds[0].refresh_from_db()
        self.assertEqual(self.beds[0].student, self.amina)

    def test_replacing_on_purpose_moves_the_other_boarder_out_and_is_logged(self):
        response = self.matron.post(f"/api/boarding/beds/{self.beds[0].id}/", {"student": self.brian.id, "replace": True},
                                    format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.beds[0].refresh_from_db()
        self.assertEqual(self.beds[0].student, self.brian)
        self.assertFalse(Bed.objects.filter(student=self.amina).exists())  # Amina now needs a bed
        self.assertTrue(ActivityLog.objects.filter(action="boarding.bed", summary__icontains="Amina").exists())

    def test_moving_into_an_empty_bed_still_works(self):
        response = self.matron.post(f"/api/boarding/beds/{self.beds[3].id}/", {"student": self.amina.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Bed.objects.get(student=self.amina), self.beds[3])


class SickBayOnLeavingTests(Fixture):
    def test_a_boarder_who_leaves_from_the_sick_bay_is_checked_out(self):
        visit = SickBayVisit.objects.create(school=self.school_a, student=self.amina, complaint="Cold",
                                            checked_in_at=timezone.now())
        release_boarders([self.amina.id], "left_school", self.admin_a)
        visit.refresh_from_db()
        self.assertIsNotNone(visit.checked_out_at)
        self.assertEqual(visit.checked_out_by_name, "Left the school")
        self.assertEqual(self.admin.get("/api/boarding/sick-bay/", {"open": 1}).data, [])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class LeaveRulesTests(Fixture):
    def setUp(self):
        super().setUp()
        quiet = User.objects.create_user(username="dad@example.test", email="dad@example.test", password="x")
        Guardian.objects.create(user=quiet, school=self.school_a, display_name="Dad",
                                email_notifications=False).students.add(self.amina)
        mum = User.objects.create_user(username="mum@example.test", email="mum@example.test", password="x")
        Guardian.objects.create(user=mum, school=self.school_a, display_name="Mum").students.add(self.amina)
        self.parent = self.authed_client(mum)
        self.leave = LeaveRequest.objects.create(school=self.school_a, student=self.amina, status="requested",
                                                 leaving_at=timezone.now() + timedelta(days=1),
                                                 returning_at=timezone.now() + timedelta(days=2), collected_by="Aunt")

    def restrict(self, client=None):
        return (client or self.admin).post("/api/boarding/restrictions/", {
            "student": self.amina.id, "leave_admin_only": True, "note": "Court order: father may not collect"},
            format="json")

    def test_only_admins_set_the_flag_and_parents_never_see_it(self):
        self.assertEqual(self.restrict(self.matron).status_code, 403)
        self.assertEqual(self.restrict().status_code, 200)
        self.assertIn(self.amina.id, [r["student"] for r in self.matron.get("/api/boarding/restrictions/").data])
        row = next(r for r in self.matron.get("/api/boarding/boarders/").data if r["id"] == self.amina.id)
        self.assertTrue(row["leave_admin_only"])
        self.assertNotIn("Court order", str(self.parent.get(f"/api/guardian-students/{self.amina.id}/boarding/").data))
        self.assertEqual(self.parent.get("/api/boarding/restrictions/").status_code, 403)
        self.assertTrue(ActivityLog.objects.filter(action="boarding.restriction").exists())
        self.assertNotIn("Court order", str(ActivityLog.objects.get(action="boarding.restriction").details))

    def test_house_staff_cannot_approve_or_give_leave_to_a_flagged_boarder(self):
        self.restrict()
        self.assertEqual(self.matron.post(f"/api/boarding/leave/{self.leave.id}/approve/").status_code, 403)
        when = timezone.now()
        self.assertEqual(self.matron.post("/api/boarding/leave/", {
            "student": self.amina.id, "kind": "weekend", "leaving_at": (when + timedelta(days=3)).isoformat(),
            "returning_at": (when + timedelta(days=4)).isoformat()}, format="json").status_code, 403)
        self.assertEqual(self.admin.post(f"/api/boarding/leave/{self.leave.id}/approve/").status_code, 200)
        self.assertEqual(self.matron.post(f"/api/boarding/leave/{self.leave.id}/sign-out/").status_code, 403)
        self.assertEqual(self.admin.post(f"/api/boarding/leave/{self.leave.id}/sign-out/").status_code, 200)

    def test_every_linked_parent_hears_about_approval_and_sign_out(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.matron.post(f"/api/boarding/leave/{self.leave.id}/approve/")
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["dad@example.test", "mum@example.test"])
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.matron.post(f"/api/boarding/leave/{self.leave.id}/sign-out/")
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["dad@example.test", "mum@example.test"])
        self.assertIn("Aunt", mail.outbox[0].body)
