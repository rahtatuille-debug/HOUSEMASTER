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
    with transaction.atomic():
        student = Student.objects.create(
            school=school, school_class=school_class, first_name=application.first_name,
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
    return student, f"{student_name(student)} is enrolled in {school_class.name}. {sentence}"
