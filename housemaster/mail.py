import logging

from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class UndeliveredEmailBackend(BaseEmailBackend):
    """
    Used in production when no email service is configured (F-18). Django's
    console backend would print every message, including password-reset and
    invite links, into the server log. This drops the message and logs an
    ERROR, which Sentry records, naming only the subject, so a missing email
    setup is noticed without leaking any link.
    """

    def send_messages(self, email_messages):
        for message in email_messages:
            logger.error(
                "Email not sent because no email service is configured (subject: %r, %d recipient(s)). "
                "Set EMAIL_BACKEND and EMAIL_HOST (docs/ENVIRONMENT.md).",
                message.subject, len(message.recipients()),
            )
        return 0
