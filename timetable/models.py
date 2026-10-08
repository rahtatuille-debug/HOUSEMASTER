"""
The school timetable, built by hand by an admin: the periods of the school
day, the rooms, and lessons (a class, a subject, a teacher and a room in one
period on one day). HouseMaster refuses clashes: a teacher or room booked
twice, or a class given two lessons at once that the same students take.
"""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import Profile
from gradebook.models import Subject
from students.models import School, SchoolClass

DAY_NAMES = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}


class SchoolWeek(models.Model):
    """Which days the school teaches on (ISO weekday numbers, Monday = 1)."""

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="school_week")
    days = models.CharField(max_length=7, default="12345")

    def day_numbers(self):
        return sorted({int(d) for d in self.days if d in "1234567"})


class Period(models.Model):
    """One slot in the school day, the same every teaching day. Breaks can't hold lessons."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="periods")
    name = models.CharField(max_length=50)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_break = models.BooleanField(default=False)

    class Meta:
        ordering = ["start_time", "id"]

    def __str__(self):
        return self.name


class Room(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["school", "name"], name="unique_room_name_per_school")]

    def __str__(self):
        return self.name


class Lesson(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="lessons")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="lessons")
    # A lesson is usually a subject; without one it is something like "Assembly" (title).
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, null=True, blank=True, related_name="lessons")
    title = models.CharField(max_length=100, blank=True)
    teacher = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons")
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons")
    day = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(7)])
    period = models.ForeignKey(Period, on_delete=models.CASCADE, related_name="lessons")

    class Meta:
        ordering = ["day", "period__start_time", "id"]
        indexes = [models.Index(fields=["school", "day", "period"])]

    @property
    def label(self):
        return self.subject.name if self.subject else (self.title or "Lesson")


class StaffAbsence(models.Model):
    """
    A teacher away for a day or more (or some periods of one day), so their
    lessons need cover. Recorded by admins or leadership. The note is for
    staff who arrange cover and is never written to the activity log.
    """

    class Reason(models.TextChoices):
        SICK = "sick", "Sick"
        TRAINING = "training", "Training or course"
        TRIP = "trip", "School trip"
        PERSONAL = "personal", "Personal or family"
        OTHER = "other", "Other"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="staff_absences")
    teacher = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="absences")
    start_date = models.DateField()
    end_date = models.DateField()
    # Empty means the whole day; otherwise only these periods (a one-day absence).
    periods = models.ManyToManyField(Period, blank=True, related_name="absences")
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.SICK)
    note = models.CharField(max_length=300, blank=True)
    recorded_by_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        indexes = [models.Index(fields=["school", "start_date", "end_date"])]

    def __str__(self):
        return f"{self.teacher.name} away {self.start_date}–{self.end_date}"


class CoverAssignment(models.Model):
    """Who covers one lesson on one date. No cover teacher means the class is supervised another way."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="cover_assignments")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="cover")
    date = models.DateField()
    cover_teacher = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="cover_lessons")
    note = models.CharField(max_length=200, blank=True, help_text='e.g. "Work set on the class page".')
    assigned_by_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "lesson__period__start_time"]
        constraints = [models.UniqueConstraint(fields=["lesson", "date"], name="one_cover_per_lesson_per_day")]
