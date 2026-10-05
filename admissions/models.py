"""
Admissions: a school's public application form (a link parents open
without an account) and the pipeline staff move each applicant through,
from a new application to enrolling them in a class (which also invites
the parent).
"""
import secrets

from django.db import models

from students.models import School, Student, YearGroup


def _token():
    return secrets.token_urlsafe(12)


class AdmissionsSettings(models.Model):
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="admissions_settings")
    is_open = models.BooleanField(default=False)
    token = models.CharField(max_length=40, unique=True, default=_token)
    intro = models.TextField(blank=True, help_text="Shown at the top of the application form.")
    # Empty: families can apply for any year group.
    year_groups = models.ManyToManyField(YearGroup, blank=True, related_name="+")
    # Keep closed applications (declined, withdrawn, enrolled) this many days after their last change, then
    # purge_applications deletes them. Empty: kept until someone deletes them (the default).
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    # Enrolling gives the new student the next free admission number: prefix + number (e.g. ADM/2026/ + 41).
    # Existing students are never renumbered; a number already in use is skipped.
    number_prefix = models.CharField(max_length=40, blank=True)
    next_number = models.PositiveIntegerField(default=1)


class Application(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEWING = "reviewing", "Reviewing"
        INTERVIEW = "interview", "Interview or test"
        OFFERED = "offered", "Offered a place"
        ACCEPTED = "accepted", "Place accepted"
        WAITLIST = "waitlist", "Waiting list"
        DECLINED = "declined", "Not offered a place"
        WITHDRAWN = "withdrawn", "Withdrawn"
        ENROLLED = "enrolled", "Enrolled"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="applications")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    year_group = models.ForeignKey(YearGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    start = models.CharField(max_length=100, blank=True, help_text="When they'd like to start, e.g. January 2027.")

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, blank=True)
    nationality = models.CharField(max_length=60, blank=True)
    current_school = models.CharField(max_length=200, blank=True)
    mode_of_learning = models.CharField(max_length=10, blank=True)  # day or boarding
    medical_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True, help_text="Anything else the family wants the school to know.")

    parent_name = models.CharField(max_length=200)
    parent_email = models.EmailField()
    parent_phone = models.CharField(max_length=40, blank=True)
    relationship = models.CharField(max_length=20, blank=True)

    staff_notes = models.TextField(blank=True, help_text="Staff only.")
    interview_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, help_text="Sent to the family with the decision.")
    decided_by_name = models.CharField(max_length=200, blank=True)
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # A new application waits until the family confirms their email address (one email, single-use link that
    # expires). Staff see it only once confirmed. Only a hash of the link's token is kept.
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirm_token = models.CharField(max_length=64, blank=True, db_index=True)
    confirm_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def reference(self):
        return f"A{self.created_at:%y}-{self.id:04d}" if self.created_at else ""
