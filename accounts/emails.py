from django.conf import settings
from django.core.mail import send_mail


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
            f"Hi {reset_token.user.username},\n\n"
            "We received a request to reset your HouseMaster password. "
            f"Click the link below to choose a new one:\n\n{reset_link}\n\n"
            "This link expires in 1 hour. If you didn't request this, you "
            "can safely ignore this email — your password won't be changed."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[reset_token.user.email],
    )
