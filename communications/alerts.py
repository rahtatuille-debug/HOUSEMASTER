"""Who receives an urgent alert."""
from django.contrib.auth.models import User
from django.db.models import Q

from .models import UrgentAlert


def alert_recipient_users(alert):
    """Active staff and/or parents at the alert's school matching its audience, minus the sender."""
    school = alert.school
    staff = Q(profile__school=school)
    parents = Q(guardian__school=school)
    audience = alert.audience
    if audience == UrgentAlert.Audience.EVERYONE:
        match = staff | parents
    elif audience == UrgentAlert.Audience.ALL_STAFF:
        match = staff
    elif audience == UrgentAlert.Audience.ALL_PARENTS:
        match = parents
    elif audience == UrgentAlert.Audience.YEAR_GROUP:
        match = parents & Q(
            guardian__students__school_class__year_group=alert.year_group, guardian__students__is_active=True
        )
    else:
        match = parents & Q(
            guardian__students__school_class=alert.school_class, guardian__students__is_active=True
        )
    users = User.objects.filter(match, is_active=True)
    if alert.created_by_id:
        users = users.exclude(id=alert.created_by_id)
    return users.distinct()


def email_alert(alert, users):
    """
    Email the alert to each recipient separately (nobody sees anyone else's
    address). Returns (sent, failed). A failure never stops the in-app alert.
    """
    import logging

    from django.conf import settings
    from django.core.mail import EmailMessage, get_connection

    from activity.services import display_name

    sender = display_name(alert.created_by) if alert.created_by else alert.school.name
    body = (
        f"URGENT from {alert.school.name}\n\n"
        f"{alert.title}\n\n"
        f"{alert.body}\n\n"
        f"Sent by {sender}.\n"
        f"Open HouseMaster to confirm you've seen this: {settings.FRONTEND_URL}\n"
    )
    messages = [
        EmailMessage(subject=f"URGENT: {alert.title} ({alert.school.name})", body=body,
                     from_email=settings.DEFAULT_FROM_EMAIL, to=[u.email])
        for u in users if u.email
    ]
    sent = 0
    try:
        with get_connection() as connection:
            for message in messages:
                try:
                    sent += connection.send_messages([message]) or 0
                except Exception:  # one bad address shouldn't stop the rest
                    logging.getLogger(__name__).exception("Urgent alert email failed")
    except Exception:
        logging.getLogger(__name__).exception("Couldn't connect to the email server for an urgent alert")
    return sent, len(messages) - sent
