from django.db import models
from students.models import Student, School


class Subject(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=100)
    # Weight in a GPA (American schools); everyone else can leave it at 1.
    credits = models.DecimalField(max_digits=4, decimal_places=1, default=1)

    class Meta:
        unique_together = ("school", "name")

    def __str__(self):
        return self.name


class Term(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="terms")
    name = models.CharField(max_length=100)  # e.g. "Term 1 2026"
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    # A locked term is finished: its grades, reports and attendance (by date)
    # can't be changed by anyone until an admin unlocks it. See gradebook.locks.
    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("school", "name")

    def __str__(self):
        return self.name


class Grade(models.Model):
    """A single assessment score for a student, in a subject, in a term."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="grades")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="grades")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="grades")
    score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["student", "term"])]

    def __str__(self):
        return f"{self.student} - {self.subject} ({self.term}): {self.score}/{self.max_score}"


class SubjectReport(models.Model):
    """
    A teacher's end-of-term entry for one student in one subject, beside the
    marks: a comment, and whatever the school's system reports per subject
    (an effort and a target grade for British schools, the four MYP criteria
    for IB schools). Printed on the report card.
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="subject_reports")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="subject_reports")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="subject_reports")
    comment = models.TextField(blank=True)
    effort = models.CharField(max_length=10, blank=True, help_text="British schools: effort grade, 1 (excellent) to 4.")
    target = models.CharField(max_length=10, blank=True, help_text="British schools: target grade, e.g. A or 7.")
    criteria = models.JSONField(default=dict, blank=True, help_text='IB MYP: {"A": 0-8, "B": 0-8, "C": 0-8, "D": 0-8}.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "subject", "term")

    def __str__(self):
        return f"{self.student} - {self.subject} ({self.term})"
