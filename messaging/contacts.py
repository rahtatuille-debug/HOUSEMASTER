"""
Who may start a conversation with whom, and which child it may be about.

These rules are the single source of truth for direct messaging. Every code
path that creates a conversation or lists contacts goes through them:

- A parent may message the staff who teach at least one of their own
  children (through TeachingAssignment) and the school's admins. Never
  another parent, and never staff who don't teach their children.
- A parent may only attach one of their own children to a conversation.
- A teacher may message parents of children in the classes they teach, and
  other staff at their school. An admin may message any parent or staff
  member at their school.
- Staff may only attach children they can see (accounts.scoping).
- Deactivated accounts and people at other schools are never reachable.

Anyone outside these rules is answered exactly like someone who doesn't
exist, so the endpoints can't be used to discover names or IDs.
"""
from django.contrib.auth.models import User
from django.db.models import Q

from accounts.models import Profile, TeachingAssignment
from accounts.scoping import assigned_class_ids, is_admin, visible_students
from students.models import Student

from .classes import guardian_class_ids


def messageable_guardian_users(staff_user):
    """
    Parents a staff member may start a conversation with: every parent at
    the school for admins, and parents of students in their own classes
    for teachers.
    """
    users = User.objects.filter(guardian__school=staff_user.profile.school, is_active=True).exclude(id=staff_user.id)
    if is_admin(staff_user):
        return users
    return users.filter(
        guardian__students__school_class_id__in=assigned_class_ids(staff_user)
    ).distinct()


def messageable_staff_for_guardian(guardian):
    """The staff a parent may message: their children's teachers and the school's admins."""
    teacher_profile_ids = TeachingAssignment.objects.filter(
        school_class_id__in=guardian_class_ids(guardian)
    ).values_list("teacher_id", flat=True)
    return User.objects.filter(
        Q(profile__id__in=teacher_profile_ids) | Q(profile__role=Profile.Role.ADMIN),
        profile__school=guardian.school,
        is_active=True,
    ).exclude(id=guardian.user_id).distinct()


def messageable_users(user):
    """Everyone `user` may start a direct conversation with (see the module docstring)."""
    guardian = getattr(user, "guardian", None)
    if guardian is not None:
        return messageable_staff_for_guardian(guardian)
    if getattr(user, "profile", None) is not None:
        staff = User.objects.filter(profile__school=user.profile.school, is_active=True).exclude(id=user.id)
        guardians = messageable_guardian_users(user)
        return User.objects.filter(Q(id__in=staff.values("id")) | Q(id__in=guardians.values("id")))
    return User.objects.none()


def contact_list(user):
    """
    The people shown in the "new message" picker: the other identity type
    (staff see parents, parents see staff), narrowed by the same rules.
    """
    guardian = getattr(user, "guardian", None)
    if guardian is not None:
        return messageable_staff_for_guardian(guardian)
    if getattr(user, "profile", None) is not None:
        return messageable_guardian_users(user)
    return User.objects.none()


def attachable_students(user):
    """The children `user` may name as the subject of a conversation."""
    guardian = getattr(user, "guardian", None)
    if guardian is not None:
        return guardian.students.all()
    if getattr(user, "profile", None) is not None:
        return visible_students(user)
    return Student.objects.none()
