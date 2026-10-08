"""
Clubs and activities: teams, societies and clubs, who is in them, their
attendance, and (for teams) fixtures and results.

Leadership and admins create clubs and choose the staff who run each one.
A club's staff manage its members, registers and fixtures. Every staff
member can see the clubs, fixtures and results; parents see their own
child's clubs, attendance and fixtures.
"""
from django.conf import settings
from django.db import models

from students.models import School, Student


class Club(models.Model):
    class Kind(models.TextChoices):
        SPORT = "sport", "Sport"
        MUSIC = "music", "Music"
        ARTS = "arts", "Drama and art"
        ACADEMIC = "academic", "Academic"
        SERVICE = "service", "Service and volunteering"
        CLUB = "club", "Club or society"
        OTHER = "other", "Other"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="clubs")
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CLUB)
    description = models.TextField(blank=True)
    meets = models.CharField(max_length=120, blank=True, help_text='When it meets, e.g. "Tuesdays 3:30pm".')
    location = models.CharField(max_length=120, blank=True)
    leaders = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="led_clubs",
                                     help_text="The staff who run it: they manage members, registers and fixtures.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["school", "name"], name="unique_club_name_per_school")]

    def __str__(self):
        return self.name


class ClubMember(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="members")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="club_memberships")
    role = models.CharField(max_length=60, blank=True, help_text='e.g. "Captain". Blank for a member.')
    joined_on = models.DateField()

    class Meta:
        ordering = ["student__last_name", "student__first_name"]
        constraints = [models.UniqueConstraint(fields=["club", "student"], name="unique_club_member")]


class ClubSession(models.Model):
    """One meeting of a club, with its register."""

    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="sessions")
    date = models.DateField()
    note = models.CharField(max_length=300, blank=True, help_text="Staff only.")
    taken_by_name = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(fields=["club", "date"], name="unique_club_session_per_day")]


class ClubAttendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        EXCUSED = "excused", "Excused"

    session = models.ForeignKey(ClubSession, on_delete=models.CASCADE, related_name="marks")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="club_attendance")
    status = models.CharField(max_length=10, choices=Status.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "student"], name="unique_club_attendance_mark")]


class Fixture(models.Model):
    """A match, competition or performance against or with another side, and its result."""

    class Venue(models.TextChoices):
        HOME = "home", "Home"
        AWAY = "away", "Away"
        NEUTRAL = "neutral", "Neutral venue"

    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="fixtures")
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    opponent = models.CharField(max_length=120, help_text="Who they play, or the event's name.")
    venue = models.CharField(max_length=10, choices=Venue.choices, default=Venue.HOME)
    location = models.CharField(max_length=200, blank=True)
    competition = models.CharField(max_length=120, blank=True, help_text='e.g. "County league".')
    team = models.CharField(max_length=60, blank=True, help_text='e.g. "Under 15 A".')
    our_score = models.PositiveSmallIntegerField(null=True, blank=True)
    their_score = models.PositiveSmallIntegerField(null=True, blank=True)
    result_note = models.CharField(max_length=300, blank=True,
                                   help_text='The result in words, e.g. "Won on penalties" or "2nd of 8".')
    report = models.TextField(blank=True, help_text="A short report. Parents of the squad see it.")
    players = models.ManyToManyField(Student, blank=True, related_name="fixtures",
                                     help_text="The squad: parents see that their child was picked.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "start_time", "id"]
        indexes = [models.Index(fields=["club", "date"])]

    def __str__(self):
        return f"{self.club} v {self.opponent} ({self.date})"

    @property
    def outcome(self):
        """win, draw or loss from the scores; None until both are in."""
        if self.our_score is None or self.their_score is None:
            return None
        if self.our_score > self.their_score:
            return "win"
        return "draw" if self.our_score == self.their_score else "loss"

    @property
    def has_result(self):
        return self.outcome is not None or bool(self.result_note)
