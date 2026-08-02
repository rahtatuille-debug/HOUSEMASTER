from django.conf import settings
from django.db import models

from students.models import School


class Profile(models.Model):
    """
    Links a Django auth User to a School, so JWT-authenticated requests
    can be scoped to the correct school's data. A school will have multiple
    staff logins (teachers, admins), so this is a ForeignKey to School.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        TEACHER = "teacher", "Teacher"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="staff_profiles")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TEACHER)

    def __str__(self):
        return f"{self.user.username} ({self.school})"
