from django.conf import settings
from django.db import models
from django.utils import timezone
import hashlib
import secrets

from students.models import School


def _generate_token():
    return secrets.token_urlsafe(24)


def _default_expiry():
    return timezone.now() + timezone.timedelta(days=7)


def username_for_email(email):
    """
    Email is now the identifier staff actually use (to log in, to receive
    invites and reset links) — but Django's built-in User model still
    requires a `username` behind the scenes. Rather than ask anyone to
    think about a separate username, this derives one from their email so
    it never surfaces in the product. `username` has a 150-char limit
    that an email can exceed, so long addresses are hashed down to fit;
    this never needs to be reversed back to the email, only to be a
    stable, unique, valid value for the column.
    """
    if len(email) <= 150:
        return email
    digest = hashlib.sha256(email.encode()).hexdigest()[:16]
    return f"{email[:130]}-{digest}"


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
        return f"{self.user.email} ({self.school})"


class Invite(models.Model):
    """
    A one-time invite link an admin generates for a new staff member. The
    school, role, and email are all fixed at creation time by the inviting
    admin — the person accepting the invite only ever chooses their own
    password, never their school, role, or the email their account will
    use to sign in (prevents a shared link from being used to self-assign
    admin rights, join a different school, or register under a different
    address than the admin intended).
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="invites")
    role = models.CharField(max_length=20, choices=Profile.Role.choices, default=Profile.Role.TEACHER)
    name = models.CharField(
        max_length=255, blank=True, help_text="Full name of the invitee — for the admin's own reference."
    )
    email = models.EmailField(help_text="The email this staff member will use to sign in.")
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


def _reset_token_expiry():
    return timezone.now() + timezone.timedelta(hours=1)


class PasswordResetToken(models.Model):
    """
    A one-time, short-lived token e-mailed to a user who asked to reset
    their password. Deliberately separate from Invite (different actor —
    an existing user rather than an admin-invited one — and a much
    shorter expiry) even though the shape is similar.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    token = models.CharField(max_length=64, unique=True, default=_generate_token, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_reset_token_expiry)
    used_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_used(self):
        return self.used_at is not None

    def __str__(self):
        return f"Password reset for {self.user.email} ({'used' if self.is_used else 'pending'})"