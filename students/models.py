from django.db import models


class School(models.Model):
    """A tenant school using HouseMaster."""
    name = models.CharField(max_length=255)
    report_tone = models.CharField(
        max_length=50,
        choices=[
            ("formal", "Formal"),
            ("warm", "Warm / encouraging"),
            ("concise", "Concise / direct"),
        ],
        default="formal",
        help_text="School-level tone setting for AI-generated report comments (v1: per-school, not per-teacher).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class YearGroup(models.Model):
    """A year/grade level within a school, e.g. 'Year 7', 'Grade 9'."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="year_groups")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = ("school", "name")

    def __str__(self):
        return f"{self.school.name} - {self.name}"


class SchoolClass(models.Model):
    """A specific class/section within a year group, e.g. '7A'."""
    year_group = models.ForeignKey(YearGroup, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField(max_length=100)
    house = models.CharField(max_length=100, blank=True)

    class Meta:
        unique_together = ("year_group", "name")

    def __str__(self):
        return f"{self.year_group.name} - {self.name}"


class Student(models.Model):
    """Core student record — the spine other modules (gradebook, attendance, reporting) hang off."""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="students")
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name="students"
    )
    external_id = models.CharField(
        max_length=100, blank=True,
        help_text="Student ID as used in the school's own Excel sheet (Students.id column), for import matching.",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    house = models.CharField(max_length=100, blank=True)
    enrolled_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["school", "external_id"])]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
