"""
Emails that bring parents in: their personal invite link, and a note when
another child is added to an account they already have. Sent in the
background after the change is saved, one email per parent.
"""
from django.conf import settings

from .notifications import _run_after_commit, _send


def _children(students):
    names = [f"{s.first_name} {s.last_name}" for s in students]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def send_invite_email(invite):
    """Email a parent the link to set up their HouseMaster account."""
    school = invite.school
    link = f"{settings.FRONTEND_URL}/guardian-invite/{invite.token}"
    students = list(invite.students.all())
    about = f" as the parent or guardian of {_children(students)}" if students else ""
    body = (
        f"Dear {invite.name or 'parent'},\n\n"
        f"{school.name} has set up a HouseMaster parent account for you{about}. HouseMaster is where you'll "
        "see reports, results, attendance and messages from the school.\n\n"
        f"To choose your password and sign in, open this link:\n\n{link}\n\n"
        f"The link works once and expires on {invite.expires_at:%d %B %Y}. If it has expired, ask the school "
        "for a new one. If you weren't expecting this email, you can ignore it."
    )
    message = (f"Your {school.name} parent account", body, invite.email)
    _run_after_commit(lambda: _send([message]))


def send_child_added_email(guardian, student):
    """Tell a parent who already has an account that another child is now linked to it."""
    body = (
        f"Dear {guardian.name},\n\n"
        f"{student.first_name} {student.last_name} has been added to your HouseMaster parent account at "
        f"{guardian.school.name}. Sign in as usual to see their reports and messages:\n\n{settings.FRONTEND_URL}"
    )
    message = (f"{student.first_name} added to your {guardian.school.name} account", body, guardian.user.email)
    _run_after_commit(lambda: _send([message]))
