"""
Safeguarding fixes for boarding (A-1, A-2, A-3, A-5):

- a missing boarder stays flagged until someone resolves it, whatever later roll calls say;
- a finished roll call is locked, and an admin's amendment is recorded with before and after;
- a boarding house with history can't be deleted (it is archived instead);
- leaving, graduating, going back to day and deactivation all free the bed.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from activity.models import ActivityLog
from students.models import School, SchoolClass, Student, YearGroup

from .models import Bed, BoardingHouse, Dorm, LeaveRequest, RollCall
from .models import Absence
from . import services



class Fixture(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        School.objects.filter(pk=self.school_a.pk).update(has_boarding=True)
        self.school_a.refresh_from_db()
        self.admin = self.authed_client(self.admin_a)
        self.matron = self.authed_client(self.user_a)  # a teacher who is staff of Uhuru House
        self.form2 = YearGroup.objects.create(school=self.school_a, name="Form 2", order=0)
        self.form4 = YearGroup.objects.create(school=self.school_a, name="Form 4", order=1, is_final=True)
        self.c2 = SchoolClass.objects.create(year_group=self.form2, name="2 East")
        self.c4 = SchoolClass.objects.create(year_group=self.form4, name="4 East")
        self.house = BoardingHouse.objects.create(school=self.school_a, name="Uhuru House")
        self.house.staff.add(self.user_a.profile)
        self.other_house = BoardingHouse.objects.create(school=self.school_a, name="Tumaini House")
        self.dorm = Dorm.objects.create(house=self.house, name="Dorm A")
        self.beds = [Bed.objects.create(dorm=self.dorm, name=f"Bed {n}") for n in (1, 2, 3, 4)]
        self.amina = self.boarder("Amina", self.c2, self.beds[0])
        self.brian = self.boarder("Brian", self.c2, self.beds[1])
        self.senior = self.boarder("Sam", self.c4, self.beds[2])
        other_dorm = Dorm.objects.create(house=self.other_house, name="Dorm X")
        self.cyrus = self.boarder("Cyrus", self.c2, Bed.objects.create(dorm=other_dorm, name="Bed 1"))
        self.nobody = User.objects.create_user(username="plain@alpha.test", email="plain@alpha.test", password="x")
        Profile.objects.create(user=self.nobody, school=self.school_a, role="teacher")  # no house
        self.plain = self.authed_client(self.nobody)
        # another school's admin
        self.make_admin(self.user_b)
        School.objects.filter(pk=self.school_b.pk).update(has_boarding=True)
        self.school_b.refresh_from_db()

    def boarder(self, name, klass, bed):
        s = Student.objects.create(school=self.school_a, first_name=name, last_name="K", school_class=klass,
                                   mode_of_learning="boarding")
        bed.student = s
        bed.save()
        return s

    def roll_call(self, session, marks, client=None, complete=True, house=None):
        """Open a roll call, mark {student: status} (everyone else present) and finish it."""
        client = client or self.matron
        house = house or self.house
        roll = client.post("/api/boarding/roll-calls/", {"house": house.id, "session": session}, format="json")
        self.assertEqual(roll.status_code, 201, roll.data)
        every = [{"student": e["student"], "status": marks.get(e["student"], "present") if not e["status"] else e["status"]}
                 for e in roll.data["entries"]]
        for entry in every:
            if entry["student"] in marks:
                entry["status"] = marks[entry["student"]]
        response = client.post(f"/api/boarding/roll-calls/{roll.data['id']}/mark/",
                               {"entries": every, "complete": complete}, format="json")
        return roll.data["id"], response

    def missing(self, client=None):
        return (client or self.matron).get("/api/boarding/overview/").data["missing"]


class MissingBoarderTests(Fixture):
    """A-1."""

    def test_a_missing_boarder_stays_flagged_when_the_next_roll_call_is_finished(self):
        self.roll_call("evening", {self.amina.id: "missing"})
        self.assertEqual([m["name"] for m in self.missing()], ["Amina K"])
        # The next roll call has everybody present (or at least doesn't say Amina is missing).
        self.roll_call("night", {})
        self.assertEqual([m["name"] for m in self.missing()], ["Amina K"])  # still open until resolved

    def test_resolving_closes_it_and_is_logged(self):
        self.roll_call("evening", {self.amina.id: "missing"})
        absence = Absence.objects.get()
        response = self.matron.post(f"/api/boarding/absences/{absence.id}/resolve/",
                                    {"resolution": "found", "note": "In the library"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["resolution_label"], "Found")
        self.assertEqual(self.missing(), [])
        absence.refresh_from_db()
        self.assertEqual((absence.status, absence.resolved_by_name != ""), ("resolved", True))
        log = ActivityLog.objects.get(action="boarding.absence_resolved")
        self.assertNotIn("library", log.summary)  # the note stays in the app
        self.assertNotIn("library", str(log.details))
        self.assertEqual(self.matron.post(f"/api/boarding/absences/{absence.id}/resolve/",
                                          {"resolution": "found"}, format="json").status_code, 400)  # only once

    def test_the_alert_lists_every_open_absence_oldest_first(self):
        self.roll_call("evening", {self.amina.id: "missing"})
        Absence.objects.filter(student=self.amina).update(opened_at=timezone.now() - timedelta(days=2))
        self.roll_call("night", {self.brian.id: "missing"})
        self.assertEqual([m["name"] for m in self.missing()], ["Amina K", "Brian K"])

    def test_resolution_has_to_be_one_of_the_known_ones(self):
        self.roll_call("evening", {self.amina.id: "missing"})
        absence = Absence.objects.get()
        self.assertEqual(self.matron.post(f"/api/boarding/absences/{absence.id}/resolve/",
                                          {"resolution": "shrugged"}, format="json").status_code, 400)

    def test_a_boarder_on_authorised_leave_is_not_flagged(self):
        LeaveRequest.objects.create(school=self.school_a, student=self.amina, status="out",
                                    leaving_at=timezone.now() - timedelta(hours=3),
                                    returning_at=timezone.now() + timedelta(days=1))
        # Approved, inside its window but not signed out yet: still authorised.
        LeaveRequest.objects.create(school=self.school_a, student=self.brian, status="approved",
                                    leaving_at=timezone.now() - timedelta(hours=1),
                                    returning_at=timezone.now() + timedelta(days=1))
        self.roll_call("evening", {self.amina.id: "missing", self.brian.id: "missing"})
        self.assertEqual(self.missing(), [])
        self.assertFalse(Absence.objects.exists())

    def test_leave_that_has_not_started_does_not_excuse_a_missing_boarder(self):
        LeaveRequest.objects.create(school=self.school_a, student=self.amina, status="approved",
                                    leaving_at=timezone.now() + timedelta(days=2),
                                    returning_at=timezone.now() + timedelta(days=4))
        self.roll_call("evening", {self.amina.id: "missing"})
        self.assertEqual([m["name"] for m in self.missing()], ["Amina K"])

    def test_two_open_absences_for_one_boarder_never_duplicate(self):
        self.roll_call("evening", {self.amina.id: "missing"})
        self.roll_call("night", {self.amina.id: "missing"})
        self.assertEqual(Absence.objects.filter(student=self.amina, status="open").count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Absence.objects.create(student=self.amina, house=self.house, status="open")

    def test_the_same_boarder_can_go_missing_again_after_being_found(self):
        self.roll_call("evening", {self.amina.id: "missing"})
        absence = Absence.objects.get()
        self.matron.post(f"/api/boarding/absences/{absence.id}/resolve/", {"resolution": "found"}, format="json")
        self.roll_call("night", {self.amina.id: "missing"})
        self.assertEqual(Absence.objects.filter(student=self.amina).count(), 2)
        self.assertEqual([m["name"] for m in self.missing()], ["Amina K"])

    def test_opening_an_absence_is_logged_without_notes(self):
        roll = self.matron.post("/api/boarding/roll-calls/", {"house": self.house.id, "session": "night"},
                                format="json").data
        self.matron.post(f"/api/boarding/roll-calls/{roll['id']}/mark/", {"entries": [
            {"student": self.amina.id, "status": "missing", "note": "Possibly with a cousin, phone 0700"},
            {"student": self.brian.id, "status": "present"}, {"student": self.senior.id, "status": "present"}],
            "complete": True}, format="json")
        log = ActivityLog.objects.get(action="boarding.absence_opened")
        self.assertNotIn("cousin", log.summary + str(log.details))

    def test_other_schools_other_houses_and_non_boarding_staff_cannot_reach_it(self):
        self.roll_call("evening", {self.amina.id: "missing"})
        absence = Absence.objects.get()
        url = f"/api/boarding/absences/{absence.id}/resolve/"
        # A teacher with no house: refused outright.
        self.assertEqual(self.plain.post(url, {"resolution": "found"}, format="json").status_code, 403)
        # Staff of a different house: not theirs.
        other = User.objects.create_user(username="tum@alpha.test", email="tum@alpha.test", password="x")
        profile = Profile.objects.create(user=other, school=self.school_a, role="teacher")
        self.other_house.staff.add(profile)
        self.assertEqual(self.authed_client(other).post(url, {"resolution": "found"}, format="json").status_code, 404)
        self.assertEqual(self.authed_client(other).get("/api/boarding/absences/").data, [])
        # Another school's admin.
        self.assertEqual(self.client_b.post(url, {"resolution": "found"}, format="json").status_code, 404)
        self.assertEqual(self.client_b.get("/api/boarding/absences/").data, [])
        absence.refresh_from_db()
        self.assertEqual(absence.status, "open")

    def test_parents_cannot_see_absences(self):
        from guardians.models import Guardian

        parent = User.objects.create_user(username="pp@alpha.test", email="pp@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)
        self.assertEqual(self.authed_client(parent).get("/api/boarding/absences/").status_code, 403)

    def test_the_backfill_opens_absences_for_what_the_old_alert_showed(self):
        from django.core.management import call_command
        from io import StringIO

        roll_id, _ = self.roll_call("evening", {self.amina.id: "missing"})
        Absence.objects.all().delete()  # how it looked before this change: only the roll call remembered
        out = StringIO()
        call_command("backfill_boarding_absences", stdout=out)
        self.assertEqual(Absence.objects.count(), 0)  # dry run by default
        self.assertIn("Would open 1", out.getvalue())
        call_command("backfill_boarding_absences", "--apply", stdout=StringIO())
        self.assertEqual([m["name"] for m in self.missing()], ["Amina K"])
        call_command("backfill_boarding_absences", "--apply", stdout=StringIO())
        self.assertEqual(Absence.objects.count(), 1)  # harmless to repeat


class FinishedRollCallTests(Fixture):
    """A-2."""

    def finished(self, marks=None):
        roll_id, _ = self.roll_call("night", marks or {})
        return roll_id

    def entries(self, roll_id):
        return {e["name"]: e["status"] for e in self.admin.get(f"/api/boarding/roll-calls/{roll_id}/").data["entries"]}

    def test_a_finished_roll_call_is_locked(self):
        roll_id = self.finished()
        marks = {"entries": [{"student": self.amina.id, "status": "missing"}]}
        self.assertEqual(self.matron.post(f"/api/boarding/roll-calls/{roll_id}/mark/", marks, format="json")
                         .status_code, 403)
        self.assertEqual(self.admin.post(f"/api/boarding/roll-calls/{roll_id}/mark/", marks, format="json")
                         .status_code, 400)  # admins use Amend, so it is on record
        self.assertEqual(self.entries(roll_id)["Amina K"], "present")

    def test_only_admins_amend_and_they_have_to_give_a_reason(self):
        roll_id = self.finished()
        body = {"entries": [{"student": self.amina.id, "status": "missing"}], "reason": "Matron misread the list"}
        self.assertEqual(self.matron.post(f"/api/boarding/roll-calls/{roll_id}/amend/", body, format="json")
                         .status_code, 403)
        self.assertEqual(self.admin.post(f"/api/boarding/roll-calls/{roll_id}/amend/",
                                         {**body, "reason": "  "}, format="json").status_code, 400)
        self.assertEqual(self.admin.post(f"/api/boarding/roll-calls/{roll_id}/amend/",
                                         {"entries": [], "reason": "x"}, format="json").status_code, 400)
        self.assertEqual(self.entries(roll_id)["Amina K"], "present")

    def test_an_amendment_is_logged_with_before_and_after(self):
        roll_id = self.finished()
        response = self.admin.post(f"/api/boarding/roll-calls/{roll_id}/amend/", {
            "entries": [{"student": self.amina.id, "status": "missing", "note": "Allergic to peanuts, was in sick bay"}],
            "reason": "Matron misread the list"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.entries(roll_id)["Amina K"], "missing")
        log = ActivityLog.objects.get(action="boarding.roll_call_amended")
        self.assertEqual(log.details["changes"], [{"student": self.amina.id, "before": "present", "after": "missing"}])
        self.assertEqual(log.actor, self.admin_a)
        text = log.summary + str(log.details)
        self.assertNotIn("peanuts", text)
        self.assertNotIn("misread", text)  # the reason is kept in the app, not in the log
        shown = self.admin.get(f"/api/boarding/roll-calls/{roll_id}/").data["amendments"]
        self.assertEqual((shown[0]["reason"], shown[0]["changes"][0]["after"]), ("Matron misread the list", "missing"))

    def test_amending_to_missing_opens_an_absence_and_back_closes_a_mistaken_one(self):
        roll_id = self.finished()
        self.admin.post(f"/api/boarding/roll-calls/{roll_id}/amend/", {
            "entries": [{"student": self.amina.id, "status": "missing"}], "reason": "Not in bed"}, format="json")
        self.assertEqual([m["name"] for m in self.missing()], ["Amina K"])
        self.admin.post(f"/api/boarding/roll-calls/{roll_id}/amend/", {
            "entries": [{"student": self.amina.id, "status": "present"}], "reason": "I was wrong"}, format="json")
        self.assertEqual(self.missing(), [])
        self.assertEqual(Absence.objects.get().resolution, "recorded_in_error")

    def test_an_unfinished_roll_call_can_still_be_marked_by_house_staff(self):
        roll_id, response = self.roll_call("morning", {self.amina.id: "missing"}, complete=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.missing(), [])  # nothing flagged until it is finished

    def test_amend_is_scoped_to_the_school(self):
        roll_id = self.finished()
        body = {"entries": [{"student": self.amina.id, "status": "missing"}], "reason": "x"}
        self.assertEqual(self.client_b.post(f"/api/boarding/roll-calls/{roll_id}/amend/", body, format="json")
                         .status_code, 404)


class HouseHistoryTests(Fixture):
    """A-3."""

    def test_a_house_with_roll_call_history_cannot_be_deleted(self):
        self.roll_call("evening", {})
        response = self.admin.delete(f"/api/boarding/houses/{self.house.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Archive", str(response.data))
        self.assertTrue(BoardingHouse.objects.filter(pk=self.house.id).exists())
        self.assertEqual(RollCall.objects.count(), 1)

    def test_the_database_refuses_it_too(self):
        from django.db.models import ProtectedError

        self.roll_call("evening", {})
        with self.assertRaises(ProtectedError):
            self.house.delete()

    def test_a_house_without_history_can_still_be_removed(self):
        self.assertEqual(self.admin.delete(f"/api/boarding/houses/{self.other_house.id}/").status_code, 204)

    def test_archiving_hides_the_house_but_keeps_its_history(self):
        roll_id, _ = self.roll_call("evening", {})
        for bed in self.beds:  # nobody sleeps there any more
            bed.student = None
            bed.save()
        response = self.admin.post(f"/api/boarding/houses/{self.house.id}/archive/")
        self.assertEqual(response.status_code, 200, response.data)
        listed = [h["name"] for h in self.admin.get("/api/boarding/houses/").data]
        self.assertNotIn("Uhuru House", listed)
        shown = [h["name"] for h in self.admin.get("/api/boarding/houses/", {"archived": 1}).data]
        self.assertIn("Uhuru House", shown)
        self.assertEqual(self.admin.get(f"/api/boarding/roll-calls/{roll_id}/").status_code, 200)  # still readable
        self.assertEqual(self.matron.get("/api/boarding/roll-calls/", {"house": self.house.id}).status_code, 200)
        new = self.admin.post("/api/boarding/roll-calls/", {"house": self.house.id, "session": "night"}, format="json")
        self.assertEqual(new.status_code, 400)
        self.assertTrue(self.admin.post(f"/api/boarding/houses/{self.house.id}/unarchive/").data["id"])

    def test_a_house_with_boarders_cannot_be_archived(self):
        response = self.admin.post(f"/api/boarding/houses/{self.house.id}/archive/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("oarders still have beds", str(response.data))

    def test_only_admins_archive_and_not_other_schools(self):
        self.assertEqual(self.matron.post(f"/api/boarding/houses/{self.other_house.id}/archive/").status_code, 403)
        self.assertEqual(self.client_b.post(f"/api/boarding/houses/{self.other_house.id}/archive/").status_code, 404)


class ReleaseBedTests(Fixture):
    """A-5."""

    def bed_of(self, student):
        return Bed.objects.filter(student=student).first()

    def test_deactivating_a_boarder_frees_the_bed(self):
        response = self.admin.patch(f"/api/students/{self.amina.id}/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(self.bed_of(self.amina))
        self.assertEqual(self.matron.get("/api/boarding/overview/").data["beds_free"], 2)  # the old spare + this one

    def test_going_back_to_day_frees_the_bed(self):
        self.admin.patch(f"/api/students/{self.amina.id}/", {"mode_of_learning": "day"}, format="json")
        self.assertIsNone(self.bed_of(self.amina))
        self.assertEqual(Student.objects.get(pk=self.amina.id).mode_of_learning, "day")

    def test_other_changes_keep_the_bed(self):
        self.admin.patch(f"/api/students/{self.amina.id}/", {"nationality": "Kenyan"}, format="json")
        self.assertIsNotNone(self.bed_of(self.amina))

    def test_year_end_graduating_and_leaving_free_beds_but_moving_up_does_not(self):
        c3 = SchoolClass.objects.create(year_group=YearGroup.objects.create(school=self.school_a, name="Form 3",
                                                                            order=2), name="3 East")
        moves = [{"from_class": self.c4.id, "to_class": None},  # graduating (final year)
                 {"from_class": self.c2.id, "to_class": c3.id}]  # moving up
        response = self.admin.post("/api/promotion/", {"moves": moves, "commit": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(self.bed_of(self.senior))
        self.assertIsNotNone(self.bed_of(self.amina))
        # Leaving from a year that isn't the last.
        c5 = SchoolClass.objects.create(year_group=self.form2, name="2 West")
        brian = Student.objects.get(pk=self.brian.id)
        Student.objects.filter(pk=brian.id).update(school_class=c5)
        self.admin.post("/api/promotion/", {"moves": [{"from_class": c5.id, "to_class": None}], "commit": True},
                        format="json")
        self.assertIsNone(self.bed_of(self.brian))

    def test_releasing_ends_open_leave_and_resolves_open_absence(self):
        self.roll_call("evening", {self.amina.id: "missing"})
        LeaveRequest.objects.create(school=self.school_a, student=self.amina, status="requested",
                                    leaving_at=timezone.now() + timedelta(days=3),
                                    returning_at=timezone.now() + timedelta(days=5))
        self.admin.patch(f"/api/students/{self.amina.id}/", {"is_active": False}, format="json")
        self.assertEqual(LeaveRequest.objects.get(student=self.amina).status, "cancelled")
        absence = Absence.objects.get(student=self.amina)
        self.assertEqual((absence.status, absence.resolution), ("resolved", "left_school"))
        self.assertTrue(ActivityLog.objects.filter(action="boarding.bed_released").exists())

    def test_the_same_function_runs_for_every_path_and_repeating_it_is_harmless(self):
        services.release_boarders([self.amina.id], reason="left_school", actor=self.admin_a)
        services.release_boarders([self.amina.id], reason="left_school", actor=self.admin_a)
        self.assertIsNone(self.bed_of(self.amina))
        self.assertEqual(ActivityLog.objects.filter(action="boarding.bed_released").count(), 1)

    def test_a_bed_left_over_from_before_still_shows_as_free_and_can_be_reused(self):
        Student.objects.filter(pk=self.amina.id).update(is_active=False)  # how old data looks
        self.assertEqual(self.matron.get("/api/boarding/overview/").data["beds_free"], 2)
        shown = self.admin.get("/api/boarding/houses/").data
        bed = next(b for h in shown for d in h["dorms"] for b in d["beds"] if b["id"] == self.beds[0].id)
        self.assertIsNone(bed["student"])
        newcomer = Student.objects.create(school=self.school_a, first_name="New", last_name="K",
                                          school_class=self.c2)
        response = self.matron.post(f"/api/boarding/beds/{self.beds[0].id}/", {"student": newcomer.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_the_sweep_command_frees_old_beds_and_is_a_dry_run_by_default(self):
        from django.core.management import call_command
        from io import StringIO

        Student.objects.filter(pk=self.amina.id).update(is_active=False)
        out = StringIO()
        call_command("release_stale_beds", stdout=out)
        self.assertIn("Would free 1", out.getvalue())
        self.assertIsNotNone(self.bed_of(self.amina))
        call_command("release_stale_beds", "--apply", stdout=StringIO())
        self.assertIsNone(self.bed_of(self.amina))

    def test_boarders_without_a_bed_are_listed(self):
        arrived = Student.objects.create(school=self.school_a, first_name="Newly", last_name="K",
                                         school_class=self.c2, mode_of_learning="boarding")
        Student.objects.create(school=self.school_a, first_name="Day", last_name="K", school_class=self.c2,
                               mode_of_learning="day")
        Student.objects.create(school=self.school_a, first_name="Gone", last_name="K", school_class=self.c2,
                               mode_of_learning="boarding", is_active=False)
        listed = self.matron.get("/api/boarding/unbedded/").data
        self.assertEqual([s["name"] for s in listed], ["Newly K"])
        self.assertEqual(self.matron.get("/api/boarding/overview/").data["unbedded"], 1)
        profile = self.admin.get(f"/api/students/{arrived.id}/profile/").data
        self.assertEqual(profile["boarding"], {"boarder_without_bed": True})
        self.assertIsNone(self.admin.get(f"/api/students/{self.amina.id}/profile/").data["boarding"])
        # Not for outsiders.
        self.assertEqual(self.plain.get("/api/boarding/unbedded/").status_code, 403)
        self.assertEqual(self.client_b.get("/api/boarding/unbedded/").data, [])

    def test_the_list_is_empty_when_boarding_is_off(self):
        School.objects.filter(pk=self.school_a.pk).update(has_boarding=False)
        self.assertEqual(self.admin.get("/api/boarding/unbedded/").status_code, 403)
        arrived = Student.objects.create(school=self.school_a, first_name="Newly", last_name="K",
                                         school_class=self.c2, mode_of_learning="boarding")
        self.assertIsNone(self.admin.get(f"/api/students/{arrived.id}/profile/").data["boarding"])
