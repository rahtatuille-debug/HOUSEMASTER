from rest_framework.permissions import BasePermission


def user_school(user):
    """Returns the school for either a staff user (via Profile) or a guardian user (via Guardian)."""
    if hasattr(user, "profile"):
        return user.profile.school
    if hasattr(user, "guardian"):
        return user.guardian.school
    return None


class CanMessage(BasePermission):
    """Either a staff Profile or a Guardian — the two identity types allowed to use messaging."""

    message = "This account isn't set up to use messaging."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile") or hasattr(request.user, "guardian")
