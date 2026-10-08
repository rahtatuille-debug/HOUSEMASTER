from rest_framework.permissions import BasePermission


class HasSchoolProfile(BasePermission):
    message = "Your account is not linked to a school."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile")


class IsSchoolAdmin(BasePermission):
    message = "Only school admins can do this."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile") and request.user.profile.role == "admin"

class IsLeader(BasePermission):
    """Admins and Leadership (accounts.scoping.is_leader)."""

    message = "Only school admins and leadership can do this."

    def has_permission(self, request, view):
        from .scoping import is_leader

        return hasattr(request.user, "profile") and is_leader(request.user)


class CanManageAdmissions(BasePermission):
    message = "Only admins and the admissions officer can do this."

    def has_permission(self, request, view):
        from .scoping import can_manage_admissions

        return hasattr(request.user, "profile") and can_manage_admissions(request.user)


class CanManageParents(BasePermission):
    message = "Only admins and the school secretary can do this."

    def has_permission(self, request, view):
        from .scoping import can_manage_parents

        return hasattr(request.user, "profile") and can_manage_parents(request.user)
