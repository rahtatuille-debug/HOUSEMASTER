"""Absence alerts to parents, and parents' absence reports reaching the register (see absences.models)."""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from students.localtime import school_localdate

from .models import AbsenceAlert, AbsenceReport, AbsenceSettings

# How far ahead a parent can report an absence, and how far back (a note after the event).
MAX_DAYS_AHEAD = 90
MAX_DAYS_BACK = 14
MAX_DAYS_LONG = 31


def alerts_enabled(school):
    row = AbsenceSettings.objects.filter(school=school).values_list("alerts_enabled", flat=True).first()
    return True if row is None else row


def covering(student_ids, day):
    """Reports (not cancelled) that cover this day for these students."""
    return AbsenceReport.objects.filter(student_id__in=student_ids, start_date__lte=day, end_date__gte=day,
                                        cancelled_at__isnull=True)


def _parents(student):
    from guardians.models import Guardian

    return list(Guardian.objects.filter(students=student, user__is_active=True).select_related("user"))


def _day(day):
    return f"{day:%A} {day.day} {day:%B}"


def _link(student, day):
    return f"{settings.FRONTEND_URL.rstrip('/')}/?absence={student.id}&date={day.isoformat()}"


def _tell(school, student, parents, subject, body_for, push_body):
    """Email the parents who get emails, and push to every device a parent turned on."""
    from communications.push import send_to_users
    from guardians.notifications import _run_after_commit, send_after_commit

    messages = [(subject, body_for(g), g.user.email) for g in parents if g.email_notifications and g.user.email]
    if messages:
        send_after_commit(messages)
    user_ids = sorted({g.user_id for g in parents})
    if user_ids:
        # No child's name in a push: it passes through the browser maker's service.
        _run_after_commit(lambda: send_to_users(user_ids, school.name, push_body, url="/"))
    return len(parents)


def after_mark(record, before):
    """
    Called when a register mark is saved. `before` is its status before (None for a new mark).
    Today's "absent" alerts the parents once; "present" or "late" after an alert sends a correction.
    """
    student = record.student
    school = student.school
    today = school_localdate(school)
    if record.date != today or before == record.status:
        return None
    if record.status == "absent":
        if not alerts_enabled(school) or covering([student.id], today).exists():
            return None
        parents = _parents(student)
        if not parents:
            return None
        try:
            with transaction.atomic():
                alert = AbsenceAlert.objects.create(student=student, date=today, parents=len(parents))
        except IntegrityError:  # already alerted today (marked absent, changed, then absent again)
            return None
        _tell(
            school, student, parents,
            f"{student.first_name} was marked absent today",
            lambda g: (f"Dear {g.name},\n\n{student.first_name} {student.last_name} was marked absent at the "
                       f"register at {school.name} today, {_day(today)}.\n\nIf you know why, please tell the "
                       f"school here: {_link(student, today)}\n\nIf you think this is a mistake, please contact "
                       f"the school.\n\nYou're receiving this because you have a parent account with {school.name}. "
                       f"You can turn these emails off on your Profile page in HouseMaster."),
            "Your child was marked absent today. Open HouseMaster to see it or tell the school why.",
        )
        return alert
    if record.status in ("present", "late") and before == "absent":
        alert = AbsenceAlert.objects.filter(student=student, date=today, corrected_at__isnull=True).first()
        if alert is None:
            return None
        alert.corrected_at = timezone.now()
        alert.save(update_fields=["corrected_at"])
        status = "present" if record.status == "present" else "late (they did arrive)"
        _tell(
            school, student, _parents(student),
            f"Update: {student.first_name} is at school today",
            lambda g: (f"Dear {g.name},\n\nSorry for the earlier message: {student.first_name} {student.last_name} "
                       f"has now been marked {status} at {school.name} today, {_day(today)}.\n\n"
                       f"You're receiving this because you have a parent account with {school.name}."),
            "Update: your child has now been marked at school today.",
        )
        return alert
    return None


def date_problem(school, start, end):
    today = school_localdate(school)
    if end < start:
        return {"end_date": ["The last day can't be before the first."]}
    if start < today - timedelta(days=MAX_DAYS_BACK):
        return {"start_date": [f"You can tell the school about an absence up to {MAX_DAYS_BACK} days afterwards."]}
    if start > today + timedelta(days=MAX_DAYS_AHEAD):
        return {"start_date": [f"You can tell the school up to {MAX_DAYS_AHEAD} days ahead."]}
    if (end - start).days >= MAX_DAYS_LONG:
        return {"end_date": [f"For an absence longer than {MAX_DAYS_LONG} days, please contact the school."]}
    return None


def class_teacher_emails(student):
    from accounts.models import StaffRole

    if student.school_class_id is None:
        return []
    return sorted(set(StaffRole.objects.filter(
        role=StaffRole.Role.CLASS_TEACHER, school_class_id=student.school_class_id,
        profile__school=student.school, profile__user__is_active=True,
    ).exclude(profile__user__email="").values_list("profile__user__email", flat=True)))


def tell_class_teachers(report):
    """A short email; the reason's details stay in HouseMaster."""
    from guardians.notifications import send_after_commit

    student = report.student
    days = (_day(report.start_date) if report.start_date == report.end_date
            else f"{_day(report.start_date)} to {_day(report.end_date)}")
    messages = [(
        f"Absence reported: {student.first_name} {student.last_name}",
        f"{report.reported_by_name} has told {student.school.name} that {student.first_name} {student.last_name} "
        f"will be away: {days} ({report.get_reason_display().lower()}).\n\nIt shows on the register. "
        f"Open HouseMaster for the details: {settings.FRONTEND_URL}",
        address,
    ) for address in class_teacher_emails(student)]
    if messages:
        send_after_commit(messages)
    return len(messages)
