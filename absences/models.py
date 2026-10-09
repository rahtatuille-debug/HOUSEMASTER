"""
Parents and absences (owner's request, 2026-10-09).

An alert: when a student is marked absent at today's register, their parents
hear the same day (email, and a push to any phone they've turned it on for),
unless a parent already told the school. If the mark is corrected to present
or late, they get a short correction.

A report: a parent tells the school their child is or will be away (ill, an
appointment...). The class's register shows it, so the teacher can mark the
child excused, and the class teacher is emailed. The details a parent types
can be about health, so they're never logged and only staff who can see the
child's attendance can read them.
"""
from django.conf import settings
from django.db import models

from students.models import School, Student


class AbsenceSettings(models.Model):
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="absence_settings")
    alerts_enabled = models.BooleanField(default=True)


class AbsenceReport(models.Model):
    class Reason(models.TextChoices):
        ILLNESS = "illness", "Ill"
        APPOINTMENT = "appointment", "Medical or dental appointment"
        FAMILY = "family", "Family reasons"
        RELIGIOUS = "religious", "Religious observance"
        TRAVEL = "travel", "Travel"
        OTHER = "other", "Other"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="absence_reports")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="absence_reports")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.CharField(max_length=500, blank=True)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    reported_by_name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    seen_by_name = models.CharField(max_length=150, blank=True)
    seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        indexes = [models.Index(fields=["school", "start_date", "end_date"])]


class AbsenceAlert(models.Model):
    """One alert per student per day, so a register saved twice doesn't email twice."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="absence_alerts")
    date = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)
    parents = models.PositiveSmallIntegerField(default=0)
    corrected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "date"], name="one_absence_alert_a_day")]
