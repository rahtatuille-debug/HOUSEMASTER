"""
Student accounts: a school-made username and starting password for a
student, who changes the password the first time they sign in.

A student sees what their parents see about them (timetable, homework,
calendar, grades and report cards, attendance, merits, behaviour records
the school shared and clubs) and nothing about anyone else. They can hand
in homework. Admins, leadership and the secretary make and manage accounts.
"""
from django.conf import settings
from django.db import models

from students.models import Student


class StudentAccount(models.Model):
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name="account")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_account")
    must_change_password = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by_name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.student} ({self.user.username})"
