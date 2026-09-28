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
- A direct conversation never mixes families: every parent in it must share
  at least one child with every other parent in it (two parents of the same
  child, yes; parents of two different children, no), so parents don't
  learn each other's names by being put in the same thread. Staff wanting
  to reach unrelated parents start separate conversations. Class notices
  and class discussions (messaging.classes) include a class's parents by
  design and don't follow this rule. There is no way to add people to a
  direct conversation after it is created.

Anyone outside these rules is answered exactly like someone who doesn't
exist, so the endpoints can't be used to discover names or IDs.
"""
from django.contrib.auth.models import User
from django.db.models import Count, Q

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


def parents_share_a_child(user_ids):
    """
    True when the parents among `user_ids` have at least one child in
    common, or when there are fewer than two parents among them.
    """
    from guardians.models import Guardian

    guardian_ids = list(Guardian.objects.filter(user_id__in=user_ids).values_list("id", flat=True))
    if len(guardian_ids) < 2:
        return True
    return Student.objects.filter(guardians__id__in=guardian_ids).annotate(
        shared_by=Count("guardians", filter=Q(guardians__id__in=guardian_ids), distinct=True)
    ).filter(shared_by=len(guardian_ids)).exists()


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
