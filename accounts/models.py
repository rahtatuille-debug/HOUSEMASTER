from django.conf import settings
from django.db import models
from django.utils import timezone
import secrets

from students.models import School


def _generate_token():
    return secrets.token_urlsafe(24)


def _default_expiry():
    return timezone.now() + timezone.timedelta(days=7)


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


class Invite(models.Model):
    """
    A one-time invite link an admin generates for a new staff member. The
    school and role are fixed at creation time by the inviting admin — the
    person accepting the invite only ever chooses their own username and
    password, never their school or role (prevents a shared link from being
    used to self-assign admin rights or join a different school).
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="invites")
    role = models.CharField(max_length=20, choices=Profile.Role.choices, default=Profile.Role.TEACHER)
    email = models.EmailField(blank=True, help_text="Optional — for the admin's own reference.")
    token = models.CharField(max_length=64, unique=True, default=_generate_token, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="invites_sent"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="invite_accepted"
    )

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_accepted(self):
        return self.accepted_at is not None

    @property
    def status(self):
        if self.is_accepted:
            return "accepted"
        if self.is_expired:
            return "expired"
        return "pending"

    def __str__(self):
        return f"Invite to {self.school} as {self.role} ({self.status})"