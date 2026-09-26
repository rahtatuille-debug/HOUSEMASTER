from django.conf import settings
from django.db import models

from students.models import School


class ActivityLog(models.Model):
    """
    One row per thing someone did that an admin might later need to answer
    "who did this, and when?" about: invites, role changes, deactivations,
    grade/attendance edits, report approvals, deletes, and so on.

    Rows are written through activity.services.log_activity() and never
    edited afterwards. `actor_name` and `summary` are stored as plain text
    at the time of the action so the log still reads correctly after the
    person, student or record it mentions is renamed or deleted.
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="activity_logs")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="activity_logs",
    )
    actor_name = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=60, help_text='e.g. "grade.updated", "staff.deactivated"')
    summary = models.CharField(max_length=500, help_text="Plain-English description of what happened.")
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["school", "-created_at"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_name}: {self.summary}"
