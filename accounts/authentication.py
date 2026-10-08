from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from .tokens import token_is_current

# A governor account is read-only and sees school-wide figures only, never a
# named student, so it may reach these and nothing else.
GOVERNOR_PATHS = ("/api/me/", "/api/governor/", "/api/logout/", "/api/tour-seen/")


class VersionedJWTAuthentication(JWTAuthentication):
    """simplejwt's JWT authentication, refusing tokens from before a password change or deactivation."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not token_is_current(validated_token, user):
            raise InvalidToken("This session has ended. Please sign in again.")
        return user

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            profile = getattr(result[0], "profile", None)
            if profile is not None and profile.role == "governor" and not request.path.startswith(GOVERNOR_PATHS):
                raise PermissionDenied("Governor accounts can only see the school's summary.")
        return result
