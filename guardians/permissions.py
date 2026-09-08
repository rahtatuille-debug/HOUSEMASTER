from rest_framework.permissions import BasePermission


class IsGuardian(BasePermission):
    message = "This account is not a guardian account."

    def has_permission(self, request, view):
        return hasattr(request.user, "guardian")
