from django.db import models
from students.models import Student


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [
        ("present", "Present"),
        ("absent", "Absent"),
        ("late", "Late"),
        ("excused", "Excused"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="attendance_records")
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="present")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("student", "date")
        indexes = [models.Index(fields=["student", "date"])]

    def __str__(self):
        return f"{self.student} - {self.date}: {self.status}"
