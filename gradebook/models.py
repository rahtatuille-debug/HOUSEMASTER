from django.db import models
from students.models import Student, School


class Subject(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=100)
    # Weight in a GPA (American schools); everyone else can leave it at 1.
    credits = models.DecimalField(max_digits=4, decimal_places=1, default=1)
    # Core subjects are taken by everyone; an elective only by students who chose it.
    is_elective = models.BooleanField(default=False)

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


class AssessmentType(models.Model):
    """
    A kind of assessment and how much it counts towards a subject's term
    result, e.g. "CAT" 30 and "End-term exam" 70. See gradebook.weighting.
    """
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="assessment_types")
    name = models.CharField(max_length=60)
    weight = models.DecimalField(max_digits=5, decimal_places=1, help_text="Its share of the term result, e.g. 30.")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ("school", "name")
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.weight:g}%)"


class Grade(models.Model):
    """A single assessment score for a student, in a subject, in a term."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="grades")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="grades")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="grades")
    score = models.DecimalField(max_digits=5, decimal_places=2)
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    assessment_type = models.ForeignKey(
        AssessmentType, on_delete=models.SET_NULL, null=True, blank=True, related_name="grades",
        help_text="Which kind of assessment this mark is from; decides its weight.",
    )
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


class StudentSubject(models.Model):
    """
    A student's choice of an elective, or the level they take a subject at
    (IB Higher or Standard Level). A student takes every core subject plus
    the electives they have a row for. See gradebook.choices.
    """
    class Level(models.TextChoices):
        NONE = "", "—"
        HL = "HL", "Higher Level"
        SL = "SL", "Standard Level"

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="subject_choices")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="student_choices")
    level = models.CharField(max_length=2, choices=Level.choices, blank=True)

    class Meta:
        unique_together = ("student", "subject")

    def __str__(self):
        return f"{self.student} takes {self.subject}{f' ({self.level})' if self.level else ''}"
