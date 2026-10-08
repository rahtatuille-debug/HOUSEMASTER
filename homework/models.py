"""
Homework and assignments: work a teacher sets a class in a subject, and how
each student did.

The teacher records each student as handed in, late, missing or excused,
with an optional mark and comment. Students can mark it done and type an
answer or paste a link (student accounts); parents see their child's
homework and how it went. Nothing is uploaded.
"""
from django.conf import settings
from django.db import models

from gradebook.models import Subject
from students.models import School, SchoolClass, Student


class Assignment(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="homework")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="homework")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="homework")
    title = models.CharField(max_length=150)
    instructions = models.TextField(blank=True)
    link = models.URLField(max_length=500, blank=True, help_text="Optional: a worksheet, video or page to use.")
    set_on = models.DateField()
    due_date = models.DateField()
    out_of = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Blank when it isn't marked out of a number.")
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    set_by_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-due_date", "-id"]
        indexes = [models.Index(fields=["school_class", "due_date"])]

    def __str__(self):
        return f"{self.school_class} {self.subject}: {self.title}"


class HomeworkRecord(models.Model):
    """How one student did on one piece of homework. Made when someone first records something."""

    class Status(models.TextChoices):
        HANDED_IN = "handed_in", "Handed in"
        LATE = "late", "Handed in late"
        MISSING = "missing", "Missing"
        EXCUSED = "excused", "Excused"

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="records")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="homework_records")
    status = models.CharField(max_length=12, choices=Status.choices, blank=True, help_text="Blank until the teacher records it.")
    mark = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    comment = models.CharField(max_length=1000, blank=True, help_text="The teacher's feedback; the student and parents see it.")
    done_at = models.DateTimeField(null=True, blank=True, help_text="When the student marked it done.")
    answer = models.TextField(blank=True, help_text="The student's typed answer or a link.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["assignment", "student"], name="unique_homework_record")]
