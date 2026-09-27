from django.conf import settings
from django.db import models
from students.models import Student
from gradebook.models import Term


class StudentReport(models.Model):
    """
    An AI-generated progress summary + draft report comment for one student, one term.

    Goes draft -> submitted (by a teacher, when they're happy with it) ->
    finalized (by an admin only). Parents only ever see finalized reports.
    An admin can send a submitted or finalized report back to draft with a
    note saying what to change. Finalized reports can't be edited or
    regenerated until they're sent back.
    """
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted for approval"),
        ("finalized", "Finalized"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="reports")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="reports")

    progress_summary = models.TextField(
        help_text="AI-generated summary of trends across terms, strengths, and areas to watch."
    )
    report_comment = models.TextField(
        help_text="AI-generated draft report comment, in the school's configured tone. Editable by teacher."
    )
    tone_used = models.CharField(
        max_length=50, blank=True,
        help_text="The School.report_tone value in effect when this was generated.",
    )
    principal_comment = models.TextField(
        blank=True, help_text="The head's remarks, printed on report cards that have them (e.g. 8-4-4). Admins only.",
    )
    extra = models.JSONField(
        default=dict, blank=True,
        help_text="Per-system ratings for the report card: CBC competencies and values, IB approaches to learning.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    review_note = models.TextField(
        blank=True, help_text="An admin's note on what to change, set when a report is sent back."
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="submitted_reports",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="finalized_reports",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)

    generated_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "term")
        indexes = [models.Index(fields=["student", "term"])]

    def __str__(self):
        return f"Report: {self.student} - {self.term} ({self.status})"
