"""
Boarding: houses with their staff, dormitories and beds; evening and night
roll calls; leave and exeat (parents ask, boarding staff decide, boarders
are signed out and back in); and sick bay visits.

Boarding staff are a house's staff (any staff member an admin adds to a
house) and admins. They see the boarders in their houses; admins see all.
"""
from django.conf import settings
from django.db import models

from accounts.models import Profile
from students.models import School, Student


class BoardingHouse(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="boarding_houses")
    name = models.CharField(max_length=100)
    staff = models.ManyToManyField(Profile, related_name="boarding_houses", blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["school", "name"], name="unique_boarding_house_name")]

    def __str__(self):
        return self.name


class Dorm(models.Model):
    house = models.ForeignKey(BoardingHouse, on_delete=models.CASCADE, related_name="dorms")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["house", "name"], name="unique_dorm_name_per_house")]

    def __str__(self):
        return self.name


class Bed(models.Model):
    dorm = models.ForeignKey(Dorm, on_delete=models.CASCADE, related_name="beds")
    name = models.CharField(max_length=50)
    student = models.OneToOneField(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name="bed")

    class Meta:
        ordering = ["dorm__name", "id"]

    def __str__(self):
        return f"{self.dorm.name} {self.name}"


class RollCall(models.Model):
    class Session(models.TextChoices):
        MORNING = "morning", "Morning"
        EVENING = "evening", "Evening"
        NIGHT = "night", "Night"

    house = models.ForeignKey(BoardingHouse, on_delete=models.CASCADE, related_name="roll_calls")
    date = models.DateField()
    session = models.CharField(max_length=10, choices=Session.choices)
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    taken_by_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["house", "date", "session"], name="one_roll_call_per_session")]


class RollCallEntry(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        MISSING = "missing", "Missing"
        ON_LEAVE = "on_leave", "On leave"
        SICK_BAY = "sick_bay", "In sick bay"

    roll_call = models.ForeignKey(RollCall, on_delete=models.CASCADE, related_name="entries")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="roll_call_entries")
    status = models.CharField(max_length=10, choices=Status.choices, blank=True)  # blank: not marked yet
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["roll_call", "student"], name="one_entry_per_boarder")]


class LeaveRequest(models.Model):
    class Kind(models.TextChoices):
        WEEKEND = "weekend", "Weekend"
        HALF_TERM = "half_term", "Half term"
        EXEAT = "exeat", "Exeat"
        APPOINTMENT = "appointment", "Appointment"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        REQUESTED = "requested", "Waiting for a decision"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"
        CANCELLED = "cancelled", "Cancelled"
        OUT = "out", "Signed out"
        RETURNED = "returned", "Back"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="leave_requests")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="leave_requests")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.WEEKEND)
    leaving_at = models.DateTimeField()
    returning_at = models.DateTimeField()
    reason = models.TextField(blank=True)
    collected_by = models.CharField(max_length=200, blank=True, help_text="Who collects the boarder.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     related_name="+")
    requested_by_name = models.CharField(max_length=200, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by_name = models.CharField(max_length=200, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    signed_out_at = models.DateTimeField(null=True, blank=True)
    signed_out_by_name = models.CharField(max_length=200, blank=True)
    signed_in_at = models.DateTimeField(null=True, blank=True)
    signed_in_by_name = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-leaving_at", "-id"]


class SickBayVisit(models.Model):
    class Outcome(models.TextChoices):
        BACK = "back", "Back to lessons or the house"
        HOME = "home", "Sent home"
        HOSPITAL = "hospital", "Sent to hospital or a clinic"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="sick_bay_visits")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="sick_bay_visits")
    checked_in_at = models.DateTimeField()
    checked_in_by_name = models.CharField(max_length=200, blank=True)
    complaint = models.TextField(help_text="Why they came, e.g. headache, fever.")
    treatment = models.TextField(blank=True, help_text="What was given or done.")
    checked_out_at = models.DateTimeField(null=True, blank=True)
    checked_out_by_name = models.CharField(max_length=200, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    parents_told_at = models.DateTimeField(null=True, blank=True)
    parents_told_how = models.CharField(max_length=200, blank=True, help_text="e.g. phoned mother, emailed.")

    class Meta:
        ordering = ["-checked_in_at", "-id"]
