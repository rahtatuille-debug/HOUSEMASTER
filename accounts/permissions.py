from rest_framework.permissions import BasePermission


class HasSchoolProfile(BasePermission):
    message = "Your account is not linked to a school."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile")


class IsSchoolAdmin(BasePermission):
    message = "Only school admins can do this."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile") and request.user.profile.role == "admin"