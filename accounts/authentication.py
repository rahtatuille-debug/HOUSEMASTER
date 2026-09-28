from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from .tokens import token_is_current


class VersionedJWTAuthentication(JWTAuthentication):
    """simplejwt's JWT authentication, refusing tokens from before a password change or deactivation."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not token_is_current(validated_token, user):
            raise InvalidToken("This session has ended. Please sign in again.")
        return user
