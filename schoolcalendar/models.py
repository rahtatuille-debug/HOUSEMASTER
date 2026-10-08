"""
The school calendar: events the school adds (holidays, exams, trips,
meetings, performances), shown with term dates and club fixtures.

Leadership, admins and the secretary add events. An event is for everyone,
for chosen year groups, or for staff only. Parents see the events for their
children's year groups; staff see every event.
"""
import secrets

from django.conf import settings
from django.db import models

from students.models import School, YearGroup


class Event(models.Model):
    class Kind(models.TextChoices):
        HOLIDAY = "holiday", "Holiday or school closed"
        EXAM = "exam", "Exams"
        MEETING = "meeting", "Parents' meeting"
        TRIP = "trip", "Trip or visit"
        SPORT = "sport", "Sport"
        PERFORMANCE = "performance", "Performance or show"
        DEADLINE = "deadline", "Deadline"
        EVENT = "event", "Event"
        STAFF = "staff", "Staff training or meeting"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="calendar_events")
    title = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.EVENT)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=150, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Blank for a one-day event.")
    start_time = models.TimeField(null=True, blank=True, help_text="Blank for all day.")
    end_time = models.TimeField(null=True, blank=True)
    year_groups = models.ManyToManyField(YearGroup, blank=True, related_name="calendar_events",
                                         help_text="Blank for the whole school.")
    staff_only = models.BooleanField(default=False, help_text="Parents and students don't see it.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_by_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_date", "start_time", "id"]
        indexes = [models.Index(fields=["school", "start_date"])]

    def __str__(self):
        return f"{self.title} ({self.start_date})"

    @property
    def last_date(self):
        return self.end_date or self.start_date


class CalendarFeed(models.Model):
    """A private link to someone's calendar for their phone or computer calendar app."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_feed")
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def new_token():
        return secrets.token_urlsafe(32)
