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

from .models import Bed, BoardingHouse, Dorm, LeaveRequest
from .models import Absence



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
