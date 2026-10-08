from rest_framework.permissions import BasePermission


class IsGuardian(BasePermission):
    message = "This account is not a guardian account."

    def has_permission(self, request, view):
        return hasattr(request.user, "guardian")


class IsGuardianOrStudent(BasePermission):
    """A parent, or a student signed in to their own account (studentaccounts)."""

    message = "This account is not a parent or student account."

    def has_permission(self, request, view):
        from studentaccounts.services import account_of

        return hasattr(request.user, "guardian") or account_of(request.user) is not None
