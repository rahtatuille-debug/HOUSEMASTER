from django.conf import settings
from django.db import models
from django.utils import timezone
import secrets

from students.models import School, Student


def _generate_token():
    return secrets.token_urlsafe(24)


def _default_expiry():
    return timezone.now() + timezone.timedelta(days=7)


class Guardian(models.Model):
    """
    A parent/guardian account. Authenticates the same way staff do (email
    + password, via the shared accounts.auth_backends.EmailBackend) but is
    a deliberately separate identity from accounts.Profile: guardians get
    a narrow permission scope (their own conversations, their own linked
    children) rather than the broad school-wide access HasSchoolProfile
    grants staff. A User is never both a Profile and a Guardian.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="guardian"
    )
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="guardians")
    display_name = models.CharField(
        max_length=255, blank=True,
        help_text="The guardian's name as shown throughout HouseMaster. Never their login email.",
    )
    students = models.ManyToManyField(Student, related_name="guardians", blank=True)

    @property
    def name(self):
        return self.display_name.strip() or self.user.get_full_name().strip() or "Guardian"

    def __str__(self):
        return f"{self.name} ({self.school})"


class GuardianInvite(models.Model):
    """
    Mirrors accounts.Invite's shape and security properties (school,
    email, and — here — the linked student(s) are all fixed by the
    inviting admin; the person accepting only ever chooses a password) but
    kept as its own model rather than extending Invite, since it creates a
    Guardian, not a Profile, and needs a student linkage Invite has no
    reason to carry.
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="guardian_invites")
    name = models.CharField(
        max_length=255, blank=True, help_text="Full name of the guardian — for the admin's own reference."
    )
    email = models.EmailField(help_text="The email this guardian will use to sign in.")
    students = models.ManyToManyField(
        Student, related_name="guardian_invites", blank=True,
        help_text="Which of the school's students this guardian will be linked to on acceptance.",
    )
    token = models.CharField(max_length=64, unique=True, default=_generate_token, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="guardian_invites_sent"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="guardian_invite_accepted",
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
        return f"Guardian invite to {self.school} ({self.status})"
