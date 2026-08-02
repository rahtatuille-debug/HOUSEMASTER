from django.db import models
from students.models import Student
from gradebook.models import Term


class StudentReport(models.Model):
    """An AI-generated progress summary + draft report comment for one student, one term."""
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("reviewed", "Reviewed / edited by teacher"),
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")

    generated_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "term")
        indexes = [models.Index(fields=["student", "term"])]

    def __str__(self):
        return f"Report: {self.student} - {self.term} ({self.status})"
