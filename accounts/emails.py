from django.conf import settings
from django.core.mail import send_mail


def send_admin_password_reset(user):
    """Email a user a password reset link on an admin's behalf. Returns the token."""
    from .models import PasswordResetToken

    reset_token = PasswordResetToken.objects.create(user=user)
    send_password_reset_email(reset_token)
    return reset_token


def send_password_reset_email(reset_token):
    """
    Sends the password reset link to the token's user. In dev, EMAIL_BACKEND
    defaults to the console backend, so this just prints to the runserver
    log — see the EMAIL_* settings for wiring up real SMTP delivery.
    """
    reset_link = f"{settings.FRONTEND_URL}/reset-password/{reset_token.token}"
    send_mail(
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
        f"HouseMaster as {'an admin' if invite.role == 'admin' else 'a teacher'}.\n\n"
        f"Create your account here (the link works until {invite.expires_at:%d %B %Y}):\n"
        f"{settings.FRONTEND_URL}/invite/{invite.token}\n"
    )
    send_after_commit([(f"You're invited to join {school.name} on HouseMaster", body, invite.email)])
