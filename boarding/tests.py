"""
Boarding: houses, dorms and beds; roll calls; leave and exeat; sick bay.
Boarding staff (a house's staff, and admins) manage their houses' boarders;
parents ask for leave and see their child's boarding records.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from guardians.models import Guardian
from students.models import SchoolClass, Student, YearGroup

from .models import Bed, BoardingHouse, Dorm, LeaveRequest, RollCall, SickBayVisit


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", NOTIFICATIONS_IN_BACKGROUND=False)
class BoardingTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        self.matron_user = self.user_a  # a teacher who is house staff
        self.matron = self.authed_client(self.matron_user)
        klass = SchoolClass.objects.create(year_group=YearGroup.objects.create(school=self.school_a, name="Form 2"),
                                           name="2 East")
        self.house = BoardingHouse.objects.create(school=self.school_a, name="Uhuru House")
        self.house.staff.add(self.user_a.profile)
        self.other_house = BoardingHouse.objects.create(school=self.school_a, name="Tumaini House")
        self.dorm = Dorm.objects.create(house=self.house, name="Dorm A")
        self.beds = [Bed.objects.create(dorm=self.dorm, name=f"Bed {n}") for n in (1, 2, 3)]
        self.amina = self.pupil("Amina", klass, self.beds[0])
        self.brian = self.pupil("Brian", klass, self.beds[1])
        other_bed = Bed.objects.create(dorm=Dorm.objects.create(house=self.other_house, name="Dorm X"), name="Bed 1")
        self.cyrus = self.pupil("Cyrus", klass, other_bed)
        self.day_kid = Student.objects.create(school=self.school_a, first_name="Dee", last_name="K", school_class=klass)
        parent = User.objects.create_user(username="p@alpha.test", email="p@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)
        self.parent = self.authed_client(parent)

    def pupil(self, name, klass, bed):
        s = Student.objects.create(school=self.school_a, first_name=name, last_name="K", school_class=klass,
                                   mode_of_learning="boarding")
        bed.student = s
        bed.save()
        return s

    # --- set-up and who can see what

    def test_admins_set_up_houses_dorms_and_beds(self):
        house = self.admin.post("/api/boarding/houses/", {"name": "Jamhuri House",
                                                         "staff": [self.matron_user.profile.id]}, format="json")
        self.assertEqual(house.status_code, 201, house.data)
        dorm = self.admin.post("/api/boarding/dorms/", {"house": house.data["id"], "name": "Dorm 1"}, format="json")
        beds = self.admin.post(f"/api/boarding/dorms/{dorm.data['id']}/beds/", {"count": 4}, format="json")
        self.assertEqual([b["name"] for b in beds.data["dorms"][0]["beds"]], ["Bed 1", "Bed 2", "Bed 3", "Bed 4"])
        self.assertEqual(self.matron.post("/api/boarding/houses/", {"name": "X"}, format="json").status_code, 403)

    def test_house_staff_see_only_their_house(self):
        names = {b["name"] for b in self.matron.get("/api/boarding/boarders/").data}
        self.assertEqual(names, {"Amina K", "Brian K"})
        self.assertEqual(len(self.admin.get("/api/boarding/boarders/").data), 3)
        self.assertTrue(self.matron.get("/api/me/").data["is_boarding_staff"])

    def test_staff_who_are_not_boarding_staff_and_parents_are_kept_out(self):
        teacher = User.objects.create_user(username="t2@alpha.test", email="t2@alpha.test", password="x")
        Profile.objects.create(user=teacher, school=self.school_a, role="teacher")
        client = self.authed_client(teacher)
        self.assertEqual(client.get("/api/boarding/boarders/").status_code, 403)
        self.assertFalse(client.get("/api/me/").data["is_boarding_staff"])
        self.assertEqual(self.parent.get("/api/boarding/boarders/").status_code, 403)

    def test_other_schools_cannot_reach_it(self):
        self.make_admin(self.user_b)
        other = self.client_b
        self.assertEqual(other.get("/api/boarding/boarders/").data, [])
        self.assertEqual(other.post(f"/api/boarding/beds/{self.beds[2].id}/", {"student": self.day_kid.id},
                                    format="json").status_code, 404)

    def test_putting_a_student_in_a_bed_and_moving_them(self):
        response = self.matron.post(f"/api/boarding/beds/{self.beds[2].id}/", {"student": self.day_kid.id},
                                    format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.day_kid.refresh_from_db()
        self.assertEqual(self.day_kid.mode_of_learning, "boarding")
        self.matron.post(f"/api/boarding/beds/{self.beds[2].id}/", {"student": self.amina.id}, format="json")
        self.assertEqual(Bed.objects.get(student=self.amina), self.beds[2])  # moved, not in two beds
        self.assertIsNone(Bed.objects.get(pk=self.beds[0].pk).student)

    # --- roll call

    def test_roll_call_fills_in_leave_and_sick_bay_and_flags_missing(self):
        LeaveRequest.objects.create(school=self.school_a, student=self.brian, status="out",
                                    leaving_at=timezone.now(), returning_at=timezone.now() + timedelta(days=1))
        roll = self.matron.post("/api/boarding/roll-calls/", {"house": self.house.id, "session": "night"},
                                format="json").data
        statuses = {e["name"]: e["status"] for e in roll["entries"]}
        self.assertEqual(statuses, {"Amina K": "", "Brian K": "on_leave"})
        unfinished = self.matron.post(f"/api/boarding/roll-calls/{roll['id']}/mark/", {"complete": True}, format="json")
        self.assertEqual(unfinished.status_code, 400)  # Amina isn't marked
        done = self.matron.post(f"/api/boarding/roll-calls/{roll['id']}/mark/", {
            "entries": [{"student": self.amina.id, "status": "missing", "note": "Not in bed"}], "complete": True},
            format="json")
        self.assertEqual(done.data["counts"], {"missing": 1, "on_leave": 1})
        missing = self.matron.get("/api/boarding/overview/").data["missing"]
        self.assertEqual([m["name"] for m in missing], ["Amina K"])
        self.assertEqual(self.matron.get("/api/teacher-home/").data["boarding"]["missing"][0]["note"], "Not in bed")

    def test_one_roll_call_per_house_session_and_day(self):
        first = self.matron.post("/api/boarding/roll-calls/", {"house": self.house.id, "session": "evening"},
                                 format="json").data["id"]
        again = self.matron.post("/api/boarding/roll-calls/", {"house": self.house.id, "session": "evening"},
                                 format="json").data["id"]
        self.assertEqual(first, again)
        self.assertEqual(RollCall.objects.count(), 1)
        self.assertEqual(self.matron.post("/api/boarding/roll-calls/", {"house": self.other_house.id,
                                                                       "session": "evening"}, format="json")
                         .status_code, 400)  # not their house

    # --- leave

    def leave_body(self, **extra):
        start = timezone.now() + timedelta(days=3)
        return {"kind": "weekend", "leaving_at": start.isoformat(),
                "returning_at": (start + timedelta(days=2)).isoformat(), "reason": "Family visit",
                "collected_by": "Mother", **extra}

    def test_parents_ask_staff_decide_and_parents_are_told(self):
        asked = self.parent.post(f"/api/guardian-students/{self.amina.id}/leave-requests/", self.leave_body(),
                                 format="json")
        self.assertEqual(asked.status_code, 201, asked.data)
        self.assertEqual(asked.data["status"], "requested")
        self.assertEqual(self.matron.get("/api/boarding/overview/").data["leave_waiting"], 1)
        with self.captureOnCommitCallbacks(execute=True):
            approved = self.matron.post(f"/api/boarding/leave/{asked.data['id']}/approve/", {}, format="json")
        self.assertEqual(approved.data["status"], "approved")
        self.assertEqual([m.to for m in mail.outbox], [["p@alpha.test"]])
        self.matron.post(f"/api/boarding/leave/{asked.data['id']}/sign-out/")
        boarders = {b["name"]: b["where"] for b in self.matron.get("/api/boarding/boarders/").data}
        self.assertEqual(boarders["Amina K"], "on_leave")
        back = self.matron.post(f"/api/boarding/leave/{asked.data['id']}/sign-in/")
        self.assertEqual(back.data["status"], "returned")
        self.assertEqual(self.matron.post(f"/api/boarding/leave/{asked.data['id']}/approve/").status_code, 400)

    def test_parents_cancel_and_see_the_decision(self):
        asked = self.parent.post(f"/api/guardian-students/{self.amina.id}/leave-requests/", self.leave_body(),
                                 format="json").data
        self.matron.post(f"/api/boarding/leave/{asked['id']}/decline/", {"note": "Exams that weekend."})
        shown = self.parent.get(f"/api/guardian-students/{self.amina.id}/boarding/").data
        self.assertEqual((shown["house"], shown["leave"][0]["status"], shown["leave"][0]["decision_note"]),
                         ("Uhuru House", "declined", "Exams that weekend."))
        again = self.parent.post(f"/api/guardian-students/{self.amina.id}/leave-requests/", self.leave_body(),
                                 format="json").data
        cancelled = self.parent.post(f"/api/guardian-students/{self.amina.id}/leave-requests/{again['id']}/cancel/")
        self.assertEqual(cancelled.data["status"], "cancelled")

    def test_leave_must_end_after_it_starts_and_is_for_boarders(self):
        bad = self.leave_body(returning_at=timezone.now().isoformat())
        self.assertEqual(self.parent.post(f"/api/guardian-students/{self.amina.id}/leave-requests/", bad,
                                          format="json").status_code, 400)
        self.assertEqual(self.matron.post("/api/boarding/leave/", {**self.leave_body(), "student": self.cyrus.id},
                                          format="json").status_code, 400)  # another house

    def test_staff_can_give_leave_directly(self):
        response = self.matron.post("/api/boarding/leave/", {**self.leave_body(), "student": self.brian.id},
                                    format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "approved")

    # --- sick bay

    def test_sick_bay_check_in_tell_parents_and_check_out(self):
        with self.captureOnCommitCallbacks(execute=True):
            visit = self.matron.post("/api/boarding/sick-bay/", {"student": self.amina.id, "complaint": "Headache",
                                                                 "treatment": "Paracetamol", "tell_parents": True},
                                     format="json")
        self.assertEqual(visit.status_code, 201, visit.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("Headache", mail.outbox[0].body)  # details stay in the app
        self.assertIsNotNone(SickBayVisit.objects.get().parents_told_at)
        self.assertEqual(self.matron.post("/api/boarding/sick-bay/", {"student": self.amina.id, "complaint": "x"},
                                          format="json").status_code, 400)  # already in
        roll = self.matron.post("/api/boarding/roll-calls/", {"house": self.house.id, "session": "evening"},
                                format="json").data
        self.assertEqual({e["name"]: e["status"] for e in roll["entries"]}["Amina K"], "sick_bay")
        out = self.matron.post(f"/api/boarding/sick-bay/{visit.data['id']}/check-out/", {"outcome": "back"},
                               format="json")
        self.assertEqual(out.data["outcome_label"], "Back to lessons or the house")
        shown = self.parent.get(f"/api/guardian-students/{self.amina.id}/boarding/").data["sick_bay"][0]
        self.assertEqual((shown["complaint"], shown["treatment"]), ("Headache", "Paracetamol"))

    def test_recording_parents_were_told_another_way(self):
        visit = self.matron.post("/api/boarding/sick-bay/", {"student": self.brian.id, "complaint": "Fever"},
                                 format="json").data
        told = self.matron.post(f"/api/boarding/sick-bay/{visit['id']}/told/", {"how": "Phoned father"},
                                format="json")
        self.assertEqual(told.data["parents_told_how"], "Phoned father")

    # --- privacy

    def test_family_export_and_removal_include_boarding(self):
        from students.privacy import family_export_data, remove_personal_data

        self.matron.post("/api/boarding/sick-bay/", {"student": self.amina.id, "complaint": "Cough"}, format="json")
        self.assertEqual(family_export_data(self.amina)["boarding"]["sick_bay"][0]["complaint"], "Cough")
        remove_personal_data(self.amina, self.admin_a)
        self.assertFalse(SickBayVisit.objects.filter(student=self.amina).exists())
        self.assertFalse(Bed.objects.filter(student=self.amina).exists())


class BoardingDemoTests(SchoolScopedAPITestCase):
    def test_demo_boarding(self):
        from .demo import fill_demo

        klass = SchoolClass.objects.create(year_group=YearGroup.objects.create(school=self.school_a, name="Form 1"),
                                           name="1 East")
        for n in range(30):
            Student.objects.create(school=self.school_a, first_name=f"S{n}", last_name="K", school_class=klass,
                                   gender="female" if n % 2 else "male")
        placed = fill_demo(self.school_a, share=0.5)
        self.assertEqual(placed, 15)
        self.assertEqual(Bed.objects.filter(student__isnull=False).count(), 15)
        self.assertTrue(LeaveRequest.objects.filter(status="requested").exists())
        self.assertTrue(SickBayVisit.objects.filter(checked_out_at__isnull=True).exists())
        self.assertTrue(RollCall.objects.filter(entries__status="missing").exists())
