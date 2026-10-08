from django.conf import settings
from django.db import models

from students.models import School, Student


class DisciplineIncident(models.Model):
    """
    One behaviour incident for a student: what happened, how serious it was
    and what the school did about it.

    Staff who can see the student see every record. Parents see a record
    only once staff share it with them, and then never the staff notes.
    """

    class Category(models.TextChoices):
        LATE = "late", "Late"
        HOMEWORK = "homework", "Homework not done"
        DISRUPTION = "disruption", "Disrupting lessons"
        UNIFORM = "uniform", "Uniform"
        PHONE = "phone", "Phone or device"
        DISRESPECT = "disrespect", "Disrespect"
        DISHONESTY = "dishonesty", "Cheating or dishonesty"
        TRUANCY = "truancy", "Skipping lessons"
        BULLYING = "bullying", "Bullying"
        FIGHTING = "fighting", "Fighting"
        DAMAGE = "damage", "Damage to property"
        SUBSTANCES = "substances", "Alcohol, drugs or smoking"
        OTHER = "other", "Other"

    class Severity(models.TextChoices):
        MINOR = "minor", "Minor"
        MODERATE = "moderate", "Moderate"
        SERIOUS = "serious", "Serious"

    class Action(models.TextChoices):
        NONE = "none", "No action yet"
        WARNING = "warning", "Warning"
        DETENTION = "detention", "Detention"
        COMMUNITY = "community", "Community work"
        MEETING = "meeting", "Meeting with parents"
        SUSPENSION = "suspension", "Suspension"
        EXCLUSION = "exclusion", "Exclusion"
        OTHER = "other", "Other"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="discipline_incidents")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="discipline_incidents")
    date = models.DateField()
    category = models.CharField(max_length=20, choices=Category.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MINOR)
    description = models.TextField(help_text="What happened. Parents see it if the record is shared.")
    action = models.CharField(max_length=20, choices=Action.choices, default=Action.NONE)
    action_detail = models.CharField(max_length=300, blank=True, help_text='e.g. "Detention Friday 3pm".')
    staff_notes = models.TextField(blank=True, help_text="Staff only; never shown to parents.")
    shared_with_parents = models.BooleanField(default=False)
    parents_notified_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    related_name="+")
    recorded_by_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["school", "-date"])]

    def __str__(self):
        return f"{self.student} {self.get_category_display()} ({self.date})"
