from rest_framework.permissions import BasePermission


class CanViewAnnouncements(BasePermission):
    """Staff and guardians can read only the announcement rows their view scopes permit."""

    message = "This account is not set up to receive announcements."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile") or hasattr(request.user, "guardian")
