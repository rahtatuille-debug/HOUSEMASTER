from django.conf import settings
from django.db import models

from students.models import School


class ChangeRequest(models.Model):
    """
    A change a teacher asked for that only takes effect once an admin
    approves it: deleting a student, changing the school's setup (year
    groups, classes, subjects, terms) or changing school settings.

    Stores the request exactly as the teacher sent it (`operation`,
    `target_id`, `data`). On approval it's replayed through the same view
    code an admin's direct change would use (approvals.services), so every
    normal check still applies at that point.
    """

    class Operation(models.TextChoices):
        CREATE = "create", "Add"
        UPDATE = "update", "Change"
        DELETE = "delete", "Delete"

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="change_requests")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="change_requests"
    )
    requested_by_name = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=30, help_text='What it changes, e.g. "student", "subject", "school".')
    operation = models.CharField(max_length=10, choices=Operation.choices)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    summary = models.CharField(max_length=500)
    reason = models.CharField(max_length=500, blank=True, help_text="Optional note from the teacher.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_change_requests",
    )
    reviewed_by_name = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.summary} ({self.get_status_display()})"
