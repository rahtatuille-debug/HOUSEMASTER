"""
B-4: each school has its own time zone, and "today" is that school's day.

A school in Nairobi, one in London and one in New York can be on different
dates at the same moment:

    22:30 UTC on 4 March 2026 is 01:30 on 5 March in Nairobi, 22:30 on
    4 March in London and 17:30 on 4 March in New York.
    00:30 UTC on 5 March 2026 is 03:30 on 5 March in Nairobi, 00:30 on
    5 March in London and 19:30 on 4 March in New York.

Django's own TIME_ZONE stays Africa/Nairobi for anything with no school.
"""
from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from accounts.models import Profile
from accounts.tests import SchoolScopedAPITestCase
from attendance.models import AttendanceRecord
from gradebook.models import Subject
from students.localtime import school_date, school_localdate, school_now
from students.models import School, SchoolClass, Student, YearGroup

LATE_EVENING_UTC = datetime(2026, 3, 4, 22, 30, tzinfo=dt_timezone.utc)
JUST_AFTER_MIDNIGHT_UTC = datetime(2026, 3, 5, 0, 30, tzinfo=dt_timezone.utc)


def at(moment):
    return patch("django.utils.timezone.now", return_value=moment)


class HelperTests(SimpleTestCase):
    def school(self, zone):
        return School(name=zone, timezone=zone)

    def test_today_differs_by_school(self):
        expected = {
            LATE_EVENING_UTC: {"Africa/Nairobi": date(2026, 3, 5), "Europe/London": date(2026, 3, 4),
                               "America/New_York": date(2026, 3, 4)},
            JUST_AFTER_MIDNIGHT_UTC: {"Africa/Nairobi": date(2026, 3, 5), "Europe/London": date(2026, 3, 5),
                                      "America/New_York": date(2026, 3, 4)},
        }
        for moment, days in expected.items():
            with at(moment):
                for zone, day in days.items():
                    self.assertEqual(school_localdate(self.school(zone)), day, (moment, zone))
                    self.assertEqual(school_now(self.school(zone)).date(), day)

    def test_school_date_of_a_stored_moment(self):
        self.assertEqual(school_date(LATE_EVENING_UTC, self.school("Africa/Nairobi")), date(2026, 3, 5))
        self.assertEqual(school_date(LATE_EVENING_UTC, self.school("America/New_York")), date(2026, 3, 4))

    def test_missing_or_unknown_zone_falls_back_to_the_default(self):
        with at(LATE_EVENING_UTC):
            self.assertEqual(school_localdate(School(name="x", timezone="")), date(2026, 3, 5))
            self.assertEqual(school_localdate(School(name="x", timezone="Not/AZone")), date(2026, 3, 5))
            self.assertEqual(school_localdate(None), date(2026, 3, 5))

    def test_django_default_stays_nairobi(self):
        self.assertEqual(settings.TIME_ZONE, "Africa/Nairobi")


class SchoolTimezoneTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.authed_client(self.admin_a)
        year = YearGroup.objects.create(school=self.school_a, name="Year 7")
        self.klass = SchoolClass.objects.create(year_group=year, name="7A")
        self.student = Student.objects.create(school=self.school_a, first_name="A", last_name="B",
                                              school_class=self.klass, date_of_birth=date(2014, 3, 5))
        self.maths = Subject.objects.create(school=self.school_a, name="Maths")

    def use_zone(self, zone):
        self.school_a.timezone = zone
        self.school_a.save(update_fields=["timezone"])

    # --- the setting ------------------------------------------------------

    def test_new_schools_default_to_nairobi(self):
        self.assertEqual(School.objects.create(name="New").timezone, "Africa/Nairobi")
        self.assertEqual(self.admin.get(f"/api/schools/{self.school_a.id}/").data["timezone"], "Africa/Nairobi")

    def test_admin_can_set_a_valid_zone(self):
        response = self.admin.patch(f"/api/schools/{self.school_a.id}/", {"timezone": "Europe/London"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.timezone, "Europe/London")

    def test_unknown_zone_is_refused(self):
        for bad in ("Mars/Olympus_Mons", "EAT", "", "africa/nairobi"):
            response = self.admin.patch(f"/api/schools/{self.school_a.id}/", {"timezone": bad}, format="json")
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("timezone", response.data)
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.timezone, "Africa/Nairobi")

    def test_a_teacher_cannot_change_it_even_through_an_approval_request(self):
        from approvals.models import ChangeRequest

        teacher = self.authed_client(self.user_a)
        response = teacher.patch(f"/api/schools/{self.school_a.id}/", {"timezone": "Europe/London"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ChangeRequest.objects.exists())
        self.school_a.refresh_from_db()
        self.assertEqual(self.school_a.timezone, "Africa/Nairobi")

    def test_another_schools_zone_is_out_of_reach(self):
        response = self.admin.patch(f"/api/schools/{self.school_b.id}/", {"timezone": "Europe/London"}, format="json")
        self.assertEqual(response.status_code, 404)

    # --- "today" follows the school -----------------------------------------

    def test_dashboard_today_is_the_schools_day(self):
        for zone, day in (("Africa/Nairobi", "2026-03-05"), ("Europe/London", "2026-03-05"),
                          ("America/New_York", "2026-03-04")):
            self.use_zone(zone)
            with at(JUST_AFTER_MIDNIGHT_UTC):
                self.assertEqual(str(self.admin.get("/api/dashboard/").data["attendance_today"]["date"]), day, zone)

    def test_attendance_bounds_follow_the_schools_own_date(self):
        # 00:30 UTC on 5 March: New York is still on 4 March, so 6 March is two
        # days ahead there (refused) but only one day ahead in London.
        for zone, status in (("Europe/London", 201), ("America/New_York", 400)):
            self.use_zone(zone)
            AttendanceRecord.objects.all().delete()
            with at(JUST_AFTER_MIDNIGHT_UTC):
                response = self.admin.post("/api/attendance/", {"student": self.student.id, "date": "2026-03-06",
                                                                "status": "present"}, format="json")
            self.assertEqual(response.status_code, status, (zone, response.data))

    def test_teacher_home_register_is_for_the_schools_day(self):
        self.assign(self.user_a, self.klass, self.maths)
        AttendanceRecord.objects.create(student=self.student, date=date(2026, 3, 4), status="present")
        teacher = self.authed_client(self.user_a)
        for zone, taken in (("America/New_York", True), ("Africa/Nairobi", False)):
            self.use_zone(zone)
            with at(JUST_AFTER_MIDNIGHT_UTC):
                home = teacher.get("/api/teacher-home/").data
            self.assertEqual(home["classes"][0]["register_taken_today"], taken, zone)

    def test_age_on_the_profile_uses_the_schools_day(self):
        # Born 5 March 2014: 12 on the school's 5 March, still 11 on 4 March.
        for zone, age in (("Africa/Nairobi", 12), ("Europe/London", 11)):
            self.use_zone(zone)
            with at(LATE_EVENING_UTC):
                profile = self.admin.get(f"/api/students/{self.student.id}/profile/").data
            self.assertEqual(profile["age"], age, zone)

    def test_graduation_date_is_the_schools_day(self):
        from students.promotion import apply_promotion

        self.klass.year_group.is_final = True
        self.klass.year_group.save()
        self.use_zone("America/New_York")
        with at(JUST_AFTER_MIDNIGHT_UTC):
            apply_promotion(self.school_a, self.admin_a, [(self.klass, None, [self.student])])
        self.student.refresh_from_db()
        self.assertEqual(self.student.graduated_on, date(2026, 3, 4))

    def test_teacher_profile_role_is_unchanged(self):
        self.assertEqual(self.user_a.profile.role, Profile.Role.TEACHER)
