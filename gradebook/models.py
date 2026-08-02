from django.db import models
from students.models import Student, School


class Subject(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ("school", "name")

    def __str__(self):
        return self.name


class Term(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="terms")
    name = models.CharField(max_length=100)  # e.g. "Term 1 2026"
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

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
