from django.contrib.auth.models import User

from accounts.scoping import assigned_class_ids, is_admin


def messageable_guardian_users(staff_user):
    """
    Parents a staff member may start a conversation with: every parent at
    the school for admins, and parents of students in their own classes
    for teachers.
    """
    users = User.objects.filter(guardian__school=staff_user.profile.school).exclude(id=staff_user.id)
    if is_admin(staff_user):
        return users
    return users.filter(
        guardian__students__school_class_id__in=assigned_class_ids(staff_user)
    ).distinct()
