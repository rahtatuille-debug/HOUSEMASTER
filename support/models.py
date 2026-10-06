from django.conf import settings
from django.db import models

from students.models import School, Student


class SupportConcern(models.Model):
    """
    A student a teacher has marked as needing support, with why, what the
    school will do (the support plan) and when to review it. HouseMaster
    only suggests students (support.services); a person always confirms.

    Parents see an open concern's reasons, note and support plan; the review
    date and dismissed suggestions stay with staff. A dismissed row only
    records that a suggestion was looked at, so it isn't suggested again
    that term.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Needs support"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Suggestion dismissed"

    class Source(models.TextChoices):
        AUTO = "auto", "Suggested by HouseMaster"
        MANUAL = "manual", "Marked by staff"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="support_concerns")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="support_concerns")
    term = models.ForeignKey("gradebook.Term", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="support_concerns")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    reasons = models.JSONField(default=list, blank=True, help_text='[{"code": "low_average", "label": "..."}]')
    note = models.TextField(blank=True, help_text="Why, in the teacher's words. Parents see it.")
    support_plan = models.TextField(blank=True, help_text="What the school will do, and how parents can help.")
    review_date = models.DateField(null=True, blank=True, help_text="When to check progress. Staff only.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name="+")
    created_by_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+")
    closed_by_name = models.CharField(max_length=255, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closing_note = models.TextField(blank=True)
    parents_notified_at = models.DateTimeField(null=True, blank=True)
    # The student's numbers when a person looked at it ({"average": %, "attendance": %}), so a dismissed
    # suggestion can come back if things get clearly worse (C-1).
    measures = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["student"], condition=models.Q(status="open"),
                                    name="one_open_support_concern_per_student"),
        ]

    def __str__(self):
        return f"{self.student} ({self.get_status_display()})"
