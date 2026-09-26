from django.conf import settings
from django.db import models
from django.utils import timezone

from students.models import School, SchoolClass, YearGroup


class Announcement(models.Model):
    """An administrative, one-way school broadcast.

    Audience rows deliberately describe the intended audience rather than a
    snapshot of recipients. This keeps the announcement usable while parent
    accounts and staff-to-class assignments are introduced in later phases.
    """

    class Audience(models.TextChoices):
        ALL_STAFF = "all_staff", "All staff"
        ALL_PARENTS = "all_parents", "All parents"
        YEAR_GROUP = "year_group", "Specific year group"
        SCHOOL_CLASS = "school_class", "Specific class"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="announcements")
    title = models.CharField(max_length=180)
    body = models.TextField()
    audience = models.CharField(max_length=20, choices=Audience.choices)
    year_group = models.ForeignKey(
        YearGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="announcements"
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name="announcements"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="announcements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["school", "status"]),
            models.Index(fields=["school", "audience"]),
        ]

    def publish(self):
        self.status = self.Status.PUBLISHED
        self.published_at = timezone.now()
        self.archived_at = None
        self.save(update_fields=["status", "published_at", "archived_at"])

    def archive(self):
        self.status = self.Status.ARCHIVED
        self.archived_at = timezone.now()
        self.save(update_fields=["status", "archived_at"])

    def __str__(self):
        return f"{self.school}: {self.title} ({self.get_status_display()})"


class UrgentAlert(models.Model):
    """
    An emergency or time-critical message (school closed, lockdown, bus
    delayed). Unlike an announcement it goes out immediately, shows as a red
    banner on every screen until each recipient taps "I've seen this", and
    records who has and hasn't seen it.

    Admins can alert any audience. Teachers can only alert the parents of a
    class they teach. The recipient list is fixed when the alert is sent
    (AlertRecipient rows), so "who hasn't seen it" is exact even if people
    join or leave afterwards.
    """

    class Audience(models.TextChoices):
        EVERYONE = "everyone", "Everyone (staff and parents)"
        ALL_STAFF = "all_staff", "All staff"
        ALL_PARENTS = "all_parents", "All parents"
        YEAR_GROUP = "year_group", "Parents of a year group"
        SCHOOL_CLASS = "school_class", "Parents of a class"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="urgent_alerts")
    title = models.CharField(max_length=180)
    body = models.TextField()
    audience = models.CharField(max_length=20, choices=Audience.choices)
    year_group = models.ForeignKey(
        YearGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="urgent_alerts"
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name="urgent_alerts"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="urgent_alerts_sent"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(
        null=True, blank=True, help_text="When the sender or an admin ended the alert; its banner then disappears."
    )

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self):
        return self.ended_at is None

    def __str__(self):
        return f"{self.school}: URGENT {self.title}"


class AlertRecipient(models.Model):
    alert = models.ForeignKey(UrgentAlert, on_delete=models.CASCADE, related_name="recipients")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="urgent_alerts")
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("alert", "user")
