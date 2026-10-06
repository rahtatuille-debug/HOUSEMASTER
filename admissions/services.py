"""Emails to families, and enrolling an accepted applicant (which invites the parent)."""
from django.contrib.auth.models import User
from django.db import transaction
from rest_framework.exceptions import ValidationError

from activity.services import log_activity, student_name
from students.models import Student

from .models import AdmissionsSettings, Application

LINES = {
    "received": "Thank you for applying to {school} for {child}. Your reference is {ref}. We will be in touch.",
    "interview": "{school} would like to meet {child}{when}.",
    "offered": "We are pleased to offer {child} a place at {school}.",
    "waitlist": "{child} is on our waiting list. We will contact you if a place becomes free.",
    "declined": "We are sorry that we can't offer {child} a place at {school} this time.",
    "enrolled": "{child} is now enrolled at {school}. You'll receive a separate email to set up your parent account.",
}


def hash_token(token):
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


def confirm_hours():
    from django.conf import settings

    return settings.ADMISSIONS_CONFIRM_HOURS


def start_confirmation(application):
    """Email the family one link to confirm the address. The email says who it's from and nothing about the
    child: anyone can type any address into a public form."""
    import secrets
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from guardians.notifications import send_after_commit

    token = secrets.token_urlsafe(32)
    application.confirm_token = hash_token(token)
    application.confirm_expires_at = timezone.now() + timedelta(hours=confirm_hours())
    application.save(update_fields=["confirm_token", "confirm_expires_at"])
    school = application.school
    body = (f"Hello,\n\nSomeone used this email address to apply for a place at {school.name}. "
            f"If it was you, confirm your email to send the application to the school:\n\n"
            f"{settings.FRONTEND_URL}/apply/confirm/{token}\n\n"
            f"The link works once and expires in {confirm_hours()} hours. If it wasn't you, ignore this email: "
            f"the application is deleted unless it's confirmed.\n\n"
            f"Sent by HouseMaster for {school.name}.")
    send_after_commit([(f"{school.name}: please confirm your email", body, application.parent_email)])


def lock_school(settings):
    """Hold the school's admissions row until the transaction ends, so two requests for the same school run
    one after the other. An UPDATE (not SELECT FOR UPDATE) so SQLite takes its write lock here as well."""
    from django.db.models import F

    AdmissionsSettings.objects.filter(pk=settings.pk).update(token=F("token"))


def find_duplicate(school, data):
    """An open application for the same child (name and date of birth) from the same email, sent recently."""
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    since = timezone.now() - timedelta(days=settings.ADMISSIONS_DUPLICATE_DAYS)
    return Application.objects.filter(
        school=school, first_name__iexact=data["first_name"].strip(), last_name__iexact=data["last_name"].strip(),
        date_of_birth=data["date_of_birth"], parent_email__iexact=data["parent_email"].strip(), created_at__gte=since,
    ).exclude(status__in=[Application.Status.DECLINED, Application.Status.WITHDRAWN]).order_by("-id").first()


def receive(form, settings):
    """A valid form from the public link: one application per child, however often it is sent (double clicks,
    two tabs, retries). A copy of an unconfirmed one whose link expired gets a fresh link; any other copy does
    nothing. The caller answers the same either way."""
    from django.utils import timezone

    with transaction.atomic():
        lock_school(settings)
        duplicate = find_duplicate(settings.school, form.validated_data)
        if duplicate is None:
            start_confirmation(form.save(school=settings.school))
        elif duplicate.confirmed_at is None and duplicate.confirm_expires_at <= timezone.now():
            start_confirmation(duplicate)


def years_old(born, on=None):
    from django.utils import timezone

    on = on or timezone.localdate()
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def typical_age(year_group):
    """The median age of the year group's current students, or None with fewer than three to go on."""
    born = sorted(Student.objects.filter(school_class__year_group=year_group, is_active=True,
                                         date_of_birth__isnull=False).values_list("date_of_birth", flat=True))
    if len(born) < 3:
        return None
    return years_old(born[len(born) // 2])


def next_admission_number(settings):
    """The next free admission number for the school. Call inside the transaction that creates the student,
    after lock_school, so two enrolments at once never get the same one (the database constraint backs this)."""
    settings.refresh_from_db(fields=["number_prefix", "next_number"])
    n = max(settings.next_number, 1)
    while Student.objects.filter(school=settings.school, external_id=f"{settings.number_prefix}{n}").exists():
        n += 1
    AdmissionsSettings.objects.filter(pk=settings.pk).update(next_number=n + 1)
    return f"{settings.number_prefix}{n}"


def existing_student(application):
    """A student at the school with the applicant's name and date of birth, if there is one."""
    if application.date_of_birth is None:
        return None
    return Student.objects.filter(school=application.school, first_name__iexact=application.first_name.strip(),
                                  last_name__iexact=application.last_name.strip(),
                                  date_of_birth=application.date_of_birth).order_by("-is_active", "id").first()


def settings_for(school):
    found, _ = AdmissionsSettings.objects.get_or_create(school=school)
    return found


def email_family(application, event):
    """Tell the family what happened. Returns 1 if an email was queued."""
    from django.utils import timezone

    from guardians.notifications import send_after_commit

    school = application.school
    when = ""
    if event == "interview" and application.interview_at:
        local = timezone.localtime(application.interview_at)
        when = f" on {local:%A %d %B at %H:%M}"
    line = LINES[event].format(school=school.name, child=application.first_name, ref=application.reference, when=when)
    if application.decision_note and event in ("interview", "offered", "waitlist", "declined"):
        line += f"\n\n{application.decision_note}"
    contact = school.email or school.phone
    body = (f"Dear {application.parent_name},\n\n{line}\n\n"
            f"{'Questions? Contact the school at ' + contact + '.' if contact else ''}\n\n{school.name}")
    send_after_commit([(f"{school.name}: application for {application.first_name}", body, application.parent_email)])
    return 1


def link_parent(school, student, application, admin):
    """Invite the parent to HouseMaster for this child, or add the child to their existing parent account."""
    from guardians.invite_emails import send_child_added_email, send_invite_email
    from guardians.models import GuardianInvite

    email = application.parent_email
    if User.objects.filter(email__iexact=email, profile__school=school).exists():
        return f"{email} belongs to a staff account, so no parent invite was sent."
    user = User.objects.filter(email__iexact=email, guardian__school=school).first()
    if user:
        user.guardian.students.add(student)
        send_child_added_email(user.guardian, student)
        return f"Added {student_name(student)} to {user.guardian.name}'s parent account."
    invite = GuardianInvite.objects.filter(school=school, email__iexact=email, accepted_at__isnull=True).first()
    if invite is None:
        invite = GuardianInvite.objects.create(school=school, name=application.parent_name, email=email,
                                               phone=application.parent_phone,
                                               relationship=application.relationship, invited_by=admin)
    else:
        invite.renew()
    invite.students.add(student)
    send_invite_email(invite)
    return f"Invited {application.parent_name} to set up a parent account."


def enrol(application, school_class, admin):
    """Make the applicant a student in the class and invite the parent. Returns (student, sentence)."""
    if application.status == Application.Status.ENROLLED:
        raise ValidationError("This applicant is already enrolled.")
    if application.status not in (Application.Status.OFFERED, Application.Status.ACCEPTED):
        raise ValidationError("Offer a place first; enrol once it's offered or accepted.")
    school = application.school
    already = existing_student(application)
    if already is not None:
        where = "is already a student here" if already.is_active else "was a student here (now inactive)"
        raise ValidationError({"detail": f"{student_name(already)}, born {already.date_of_birth:%d %b %Y}, {where}. "
                                         "Open their student page instead of enrolling them again"
                                         f"{'' if already.is_active else ' (reactivate them there)'}.",
                               "existing_student": already.id})
    with transaction.atomic():
        found = settings_for(school)
        lock_school(found)
        student = Student.objects.create(
            school=school, school_class=school_class, external_id=next_admission_number(found),
            first_name=application.first_name,
            last_name=application.last_name, date_of_birth=application.date_of_birth,
            gender=application.gender if application.gender in ("female", "male", "other") else "",
            nationality=application.nationality, medical_notes=application.medical_notes,
            mode_of_learning=application.mode_of_learning if application.mode_of_learning in ("day", "boarding") else "",
        )
        application.status = Application.Status.ENROLLED
        application.student = student
        application.save(update_fields=["status", "student", "updated_at"])
        sentence = link_parent(school, student, application, admin)
        email_family(application, "enrolled")
        log_activity(school=school, actor=admin, action="admissions.enrolled", target=student,
                     summary=f"Enrolled {student_name(student)} in {school_class.name} from admissions")
    return student, (f"{student_name(student)} is enrolled in {school_class.name} with admission number "
                     f"{student.external_id}. {sentence}")


def applications_about(student):
    """The admissions applications held about a student: the one they were enrolled from, and any other for the
    same child (name and date of birth) at the same school, e.g. an earlier one that was declined."""
    from django.db.models import Q

    same_child = Q(student=student)
    if student.date_of_birth:
        same_child |= Q(first_name__iexact=student.first_name.strip(), last_name__iexact=student.last_name.strip(),
                        date_of_birth=student.date_of_birth)
    return Application.objects.filter(same_child, school=student.school).select_related("year_group")


def application_row(a):
    return {
        "reference": a.reference, "status": a.get_status_display(), "year_group": a.year_group.name if a.year_group else "",
        "start": a.start, "sent": a.created_at.isoformat() if a.created_at else None,
        "email_confirmed": a.confirmed_at.isoformat() if a.confirmed_at else None,
        "first_name": a.first_name, "last_name": a.last_name,
        "date_of_birth": a.date_of_birth.isoformat() if a.date_of_birth else None, "gender": a.gender,
        "nationality": a.nationality, "current_school": a.current_school, "mode_of_learning": a.mode_of_learning,
        "needs_to_discuss": a.has_needs, "health_and_learning_needs": a.medical_notes, "family_notes": a.notes, "parent_name": a.parent_name,
        "parent_email": a.parent_email, "parent_phone": a.parent_phone, "relationship": a.relationship,
        "interview": a.interview_at.isoformat() if a.interview_at else None, "decision_note": a.decision_note,
        "staff_notes": a.staff_notes,
    }

