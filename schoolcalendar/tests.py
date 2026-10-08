"""
School calendar (owner's request, 2026-10-08): events the school adds,
term dates and club fixtures, for staff and parents, and as a private
calendar-app link.
"""
from datetime import time, timedelta

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from accounts.test_roles import RoleFixture
from activity.models import ActivityLog
from clubs.models import Club, ClubMember, Fixture
from gradebook.models import Term
from guardians.models import Guardian
from students.localtime import school_localdate

from .models import CalendarFeed, Event

URL = "/api/calendar/"
EVENTS = "/api/calendar/events/"


class Base(RoleFixture):
    def setUp(self):
        super().setUp()
        self.today = school_localdate(self.school_a)
        self.lead = self.staff("lead@alpha.test", "teacher", "leadership")[1]
        self.secretary = self.staff("sec@alpha.test", "teacher", "secretary")[1]
        parent = User.objects.create_user(username="pa@alpha.test", email="pa@alpha.test", password="x")
        Guardian.objects.create(user=parent, school=self.school_a, display_name="Pat").students.add(self.amina)  # Form 2
        self.parent = self.authed_client(parent)
        self.window = {"from": (self.today - timedelta(days=5)).isoformat(), "to": (self.today + timedelta(days=30)).isoformat()}

    def add(self, client=None, **extra):
        body = {"title": "Sports day", "kind": "sport", "start_date": (self.today + timedelta(days=3)).isoformat(), **extra}
        return (client or self.lead).post(EVENTS, body, format="json")

    def titles(self, client):
        return [i["title"] for i in client.get(URL, self.window).data["items"]]


class EventTests(Base):
    def test_leadership_and_the_secretary_add_events_teachers_cannot(self):
        response = self.add(location="Main field", start_time="09:00", end_time="15:00")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["kind_label"], response.data["year_groups"]), ("Sport", []))
        self.assertEqual(self.add(self.secretary, title="Photos").status_code, 201)
        self.assertEqual(self.add(self.client_a, title="Party").status_code, 403)
        eid = Event.objects.get(title="Sports day").id
        self.assertEqual(self.client_a.patch(f"{EVENTS}{eid}/", {"title": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client_a.delete(f"{EVENTS}{eid}/").status_code, 403)
        self.assertTrue(ActivityLog.objects.filter(action="calendar.event_added").exists())

    def test_bad_events(self):
        later, sooner = (self.today + timedelta(days=5)).isoformat(), self.today.isoformat()
        self.assertEqual(self.add(start_date=later, end_date=sooner).status_code, 400)
        self.assertEqual(self.add(end_time="10:00").status_code, 400)
        self.assertEqual(self.add(start_time="10:00", end_time="09:00").status_code, 400)
        self.assertEqual(self.add(title=" ").status_code, 400)
        self.assertEqual(self.add(year_groups=[999999]).status_code, 400)
        self.assertEqual(Event.objects.count(), 0)

    def test_staff_see_everything_parents_see_their_childs_year_and_never_staff_only(self):
        self.add(title="Whole school")
        self.add(title="Form 2 trip", kind="trip", year_groups=[self.form2.id])
        self.add(title="Form 3 exams", kind="exam", year_groups=[self.form3.id])
        self.add(title="INSET day", kind="staff", staff_only=True)
        self.assertEqual(sorted(self.titles(self.client_a)), ["Form 2 trip", "Form 3 exams", "INSET day", "Whole school"])
        self.assertEqual(sorted(self.titles(self.parent)), ["Form 2 trip", "Whole school"])
        self.assertFalse(any(i["can_edit"] for i in self.client_a.get(URL, self.window).data["items"]))
        data = self.lead.get(URL, self.window).data
        self.assertTrue(data["can_manage"] and all(i["can_edit"] for i in data["items"]))
        self.assertEqual([y["name"] for y in data["year_groups"]], ["Form 2", "Form 3"])

    def test_multi_day_events_overlapping_the_window_show(self):
        Event.objects.create(school=self.school_a, title="Half term", kind="holiday",
                             start_date=self.today - timedelta(days=20), end_date=self.today + timedelta(days=1))
        Event.objects.create(school=self.school_a, title="Long ago", start_date=self.today - timedelta(days=60))
        self.assertEqual(self.titles(self.parent), ["Half term"])

    def test_term_dates_and_fixtures(self):
        Term.objects.create(school=self.school_a, name="Term 2", start_date=self.today + timedelta(days=10),
                            end_date=self.today + timedelta(days=100))
        club = Club.objects.create(school=self.school_a, name="Football")
        other = Club.objects.create(school=self.school_a, name="Chess")
        ClubMember.objects.create(club=club, student=self.amina, joined_on=self.today)
        f = Fixture.objects.create(club=club, date=self.today + timedelta(days=2), opponent="Hill", start_time=time(14))
        f.players.add(self.amina)
        Fixture.objects.create(club=other, date=self.today + timedelta(days=2), opponent="Elsewhere")
        self.assertEqual(self.titles(self.parent), ["Football v Hill", "Term 2 starts"])
        (fixture,) = [i for i in self.parent.get(URL, self.window).data["items"] if i["type"] == "fixture"]
        self.assertEqual(fixture["picked"], ["Amina"])
        self.assertIn("Chess v Elsewhere", self.titles(self.client_a))

    def test_bad_windows(self):
        self.assertEqual(self.parent.get(URL, {"from": "soon"}).status_code, 400)
        self.assertEqual(self.parent.get(URL, {"from": "2026-01-01", "to": "2028-01-01"}).status_code, 400)
        self.assertEqual(self.parent.get(URL, {"from": "2026-02-01", "to": "2026-01-01"}).status_code, 400)
        self.assertEqual(self.parent.get(URL).status_code, 200)


class FeedTests(Base):
    def test_a_private_link_for_calendar_apps(self):
        self.add(title="Sports day, with races; and fun", location="Main field", start_time="09:00")
        self.add(title="Staff only", staff_only=True)
        url = self.parent.get(f"{URL}feed/").data["url"]
        token = url.rsplit("/", 1)[1].removesuffix(".ics")
        self.assertEqual(self.parent.get(f"{URL}feed/").data["url"], url)  # the same link each time
        response = APIClient().get(f"/api/calendar/ical/{token}.ics")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        body = response.content.decode()
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn(r"SUMMARY:Sports day\, with races\; and fun", body)
        self.assertIn("LOCATION:Main field", body)
        self.assertNotIn("Staff only", body)
        # A new link replaces the old one.
        self.parent.post(f"{URL}feed/")
        self.assertEqual(APIClient().get(f"/api/calendar/ical/{token}.ics").status_code, 404)

    def test_unknown_or_disabled_links(self):
        self.assertEqual(APIClient().get("/api/calendar/ical/nope.ics").status_code, 404)
        url = self.client_a.get(f"{URL}feed/").data["url"]
        self.user_a.is_active = False
        self.user_a.save()
        self.assertEqual(APIClient().get(url.split("testserver")[1]).status_code, 404)

    def test_all_day_and_multi_day_events_in_ics(self):
        from .services import ical

        first = self.today + timedelta(days=10)
        Event.objects.create(school=self.school_a, title="Half term " + "very long words " * 8, kind="holiday",
                             start_date=first, end_date=first + timedelta(days=4))
        body = ical(self.user_a, self.school_a, "example.test")
        self.assertIn(f"DTSTART;VALUE=DATE:{first:%Y%m%d}", body)
        self.assertIn(f"DTEND;VALUE=DATE:{first + timedelta(days=5):%Y%m%d}", body)  # the day after the last day
        self.assertTrue(all(len(line.encode()) <= 75 for line in body.split("\r\n")))
        self.assertIn("\r\n ", body)  # the long title is folded onto a continuation line


class IsolationTests(Base):
    def setUp(self):
        super().setUp()
        self.event = Event.objects.create(school=self.school_a, title="Alpha secret", start_date=self.today)
        self.make_admin(self.user_b)

    def test_another_school_sees_and_changes_nothing(self):
        self.assertNotIn("Alpha secret", str(self.client_b.get(URL).data))
        self.assertEqual(self.client_b.get(EVENTS).data, [])
        self.assertEqual(self.client_b.patch(f"{EVENTS}{self.event.id}/", {"title": "X"}, format="json").status_code, 404)
        self.assertEqual(self.client_b.delete(f"{EVENTS}{self.event.id}/").status_code, 404)
        self.assertEqual(self.client_b.post(EVENTS, {"title": "X", "start_date": self.today.isoformat(),
                                                     "year_groups": [self.form2.id]}, format="json").status_code, 400)

    def test_the_public_parents_api_and_governors(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
        self.assertEqual(APIClient().get(f"{URL}feed/").status_code, 401)
        self.assertEqual(self.parent.get(EVENTS).status_code, 403)
        gov = self.staff("gov@alpha.test", "governor")[1]
        self.assertEqual(gov.get(URL).status_code, 403)
        CalendarFeed.objects.create(user=User.objects.get(username="gov@alpha.test"), token="govtoken")
        self.assertEqual(APIClient().get("/api/calendar/ical/govtoken.ics").status_code, 404)


class DemoTests(Base):
    def test_demo_events_once(self):
        from .demo import fill_demo

        self.assertEqual(fill_demo(self.school_a), 7)
        self.assertEqual(fill_demo(self.school_a), 0)
        self.assertTrue(Event.objects.filter(staff_only=True).exists())
