from rest_framework.permissions import BasePermission


class HasSchoolProfile(BasePermission):
    """
    Requires that the authenticated user has a Profile linking them to a
    School. Combine with IsAuthenticated (set as the DRF default) — this
    permission assumes the user is already authenticated and just checks
    they're actually staff at a school, not e.g. a bare superuser account
    created without a Profile.
    """

    message = "Your account is not linked to a school."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile")
