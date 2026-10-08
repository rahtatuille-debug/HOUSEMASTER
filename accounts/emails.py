import logging

from django.conf import settings
from django.core.mail import send_mail
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class ResetEmailNotSent(APIException):
    status_code = 503
    default_detail = "The reset email couldn't be sent. Check the email settings, or try again later."
    default_code = "email_not_sent"


ROLE_WORDS = {"admin": "an admin", "teacher": "a teacher", "governor": "a governor (read-only)"}


def send_admin_password_reset(user):
    """
    Email a user a password reset link on an admin's behalf. Returns the
    token. Unlike the public reset form, the admin is told if it wasn't sent.
    """
    from .models import PasswordResetToken

    reset_token = PasswordResetToken.objects.create(user=user)
    if not send_password_reset_email(reset_token):
        raise ResetEmailNotSent()
    return reset_token


def send_password_reset_email(reset_token):
    """
    Sends the password reset link to the token's user. In dev, EMAIL_BACKEND
    defaults to the console backend, so this just prints to the runserver
    log — see the EMAIL_* settings for wiring up real SMTP delivery.
    """
    reset_link = f"{settings.FRONTEND_URL}/reset-password/{reset_token.token}"
    try:
        return _send_reset(reset_token, reset_link) > 0
    except Exception:
        # Logged for Sentry without the link. The public reset form still
        # gets its usual answer: a 500 here, only for real accounts, would
        # reveal which emails have one. Returns whether it was sent.
        logger.exception("Password reset email for user %s could not be sent", reset_token.user_id)
        return False


def _send_reset(reset_token, reset_link):
    return send_mail(
        subject="Reset your HouseMaster password",
        message=(
            f"Hi {reset_token.user.email},\n\n"
            "We received a request to reset your HouseMaster password. "
            f"Click the link below to choose a new one:\n\n{reset_link}\n\n"
            "This link expires in 1 hour. If you didn't request this, you "
            "can safely ignore this email — your password won't be changed."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[reset_token.user.email],
    )


def send_staff_invite_email(invite, invited_by_name):
    """Email a staff member their invite link, once the invite is saved (in the background)."""
    from guardians.notifications import send_after_commit

    school = invite.school
    body = (
        f"Hello {invite.name or 'there'},\n\n{invited_by_name} has invited you to join {school.name} on "
        f"HouseMaster as {ROLE_WORDS.get(invite.role, 'a member of staff')}.\n\n"
        f"Create your account here (the link works until {invite.expires_at:%d %B %Y}):\n"
        f"{settings.FRONTEND_URL}/invite/{invite.token}\n"
    )
    send_after_commit([(f"You're invited to join {school.name} on HouseMaster", body, invite.email)])
