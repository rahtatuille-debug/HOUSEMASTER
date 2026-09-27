"""
Email parents when something new is published for them: an announcement to
their child's class, year group or the whole school, or a finalized report.

Each parent gets their own email (nobody sees anyone else's address), only
parents who haven't turned emails off are included, and sending happens in
the background so publishing to a whole school doesn't hold up the request.
A failed email never undoes the publish itself.
"""
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, transaction

from activity.services import log_activity

from .models import Guardian

logger = logging.getLogger(__name__)


def _run_after_commit(fn):
    """Run `fn` once the current transaction commits, off the request thread in production."""
    def start():
        if not getattr(settings, "NOTIFICATIONS_IN_BACKGROUND", True):
            fn()
            return

        def work():
            try:
                fn()
            finally:
                close_old_connections()

        threading.Thread(target=work, daemon=True).start()

    transaction.on_commit(start)


# Reserved domains that can never receive mail (the demo school uses one), so
# sending to them would only produce bounces.
UNDELIVERABLE = (".example", ".invalid")


def _send(messages):
    """Send (subject, body, address) triples one by one. Returns (sent, attempted)."""
    from django.core.mail import EmailMessage, get_connection

    messages = [m for m in messages if not m[2].lower().endswith(UNDELIVERABLE)]
    sent = 0
    try:
        with get_connection() as connection:
            for subject, body, address in messages:
                try:
                    sent += connection.send_messages([EmailMessage(
                        subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[address],
                    )]) or 0
                except Exception:  # one bad address shouldn't stop the rest
                    logger.exception("Parent notification email failed")
    except Exception:
        logger.exception("Couldn't connect to the email server for parent notifications")
    return sent, len(messages)


def _footer(school):
    return (
        f"\n\nOpen HouseMaster to read it: {settings.FRONTEND_URL}\n\n"
        f"You're receiving this because you have a parent account with {school.name}. "
        f"You can turn these emails off on your Profile page in HouseMaster."
    )


def announcement_recipients(announcement):
    """Parents who should hear about this announcement, or none for staff-only ones."""
    from communications.models import Announcement

    parents = Guardian.objects.filter(
        school=announcement.school, email_notifications=True, user__is_active=True,
    ).exclude(user__email="")
    audience = announcement.audience
    if audience == Announcement.Audience.ALL_PARENTS:
        return parents
    if audience == Announcement.Audience.YEAR_GROUP:
        return parents.filter(students__school_class__year_group=announcement.year_group,
                              students__is_active=True).distinct()
    if audience == Announcement.Audience.SCHOOL_CLASS:
        return parents.filter(students__school_class=announcement.school_class,
                              students__is_active=True).distinct()
    return Guardian.objects.none()


def notify_announcement_published(announcement, actor):
    school = announcement.school
    recipients = list(announcement_recipients(announcement).select_related("user"))
    if not recipients:
        return
    subject = f"{school.name}: {announcement.title}"
    body = f"{announcement.title}\n\n{announcement.body}" + _footer(school)
    messages = [(subject, body, g.user.email) for g in recipients]

    def send():
        sent, attempted = _send(messages)
        if not attempted:
            return
        log_activity(
            school=school, actor=actor, action="notification.emailed", target=announcement,
            summary=f'Emailed {sent} of {attempted} parents about "{announcement.title}"',
        )

    _run_after_commit(send)


def notify_reports_finalized(reports, actor):
    """Tell each parent that their child's report is ready. The report itself stays in the app."""
    reports = list(reports)
    if not reports:
        return
    school = reports[0].student.school
    guardians = Guardian.objects.filter(
        students__in=[r.student_id for r in reports], email_notifications=True, user__is_active=True,
    ).exclude(user__email="").select_related("user").prefetch_related("students").distinct()
    by_student = {r.student_id: r for r in reports}
    messages = []
    for g in guardians:
        for child in g.students.all():
            report = by_student.get(child.id)
            if report is None:
                continue
            subject = f"{child.first_name}'s {report.term.name} report is ready"
            body = (
                f"Dear {g.name},\n\n{child.first_name} {child.last_name}'s {report.term.name} report from "
                f"{school.name} is now available. You can read it and download the report card in HouseMaster."
                + _footer(school)
            )
            messages.append((subject, body, g.user.email))
    if not messages:
        return

    def send():
        sent, attempted = _send(messages)
        if not attempted:
            return
        term = reports[0].term.name
        log_activity(
            school=school, actor=actor, action="notification.emailed",
            summary=f"Emailed {sent} of {attempted} parents that {term} reports are ready",
        )

    _run_after_commit(send)
