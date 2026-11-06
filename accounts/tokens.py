"""
Login tokens that die when the account's password changes or it is
deactivated.

Every token carries the user's current `token_version` in the `tv` claim.
accounts/signals.py moves the version on whenever the password changes
(set_password, a reset, the admin) or the account is deactivated, and
VersionedJWTAuthentication / VersionedTokenRefreshSerializer refuse any
token whose version is out of date. Tokens issued before this existed
have no claim and count as version 0, so deploying it signs nobody out.
"""
from django.contrib.auth import get_user_model
from django.db.models import F
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from .models import UserSecurity

TOKEN_VERSION_CLAIM = "tv"


def current_token_version(user):
    return UserSecurity.objects.filter(user_id=user.pk).values_list("token_version", flat=True).first() or 0


def bump_token_version(user_id):
    """End every session this user has open."""
    if not UserSecurity.objects.filter(user_id=user_id).update(token_version=F("token_version") + 1):
        security, created = UserSecurity.objects.get_or_create(user_id=user_id, defaults={"token_version": 1})
        if not created:
            UserSecurity.objects.filter(pk=security.pk).update(token_version=F("token_version") + 1)


def token_is_current(token, user):
    return token.get(TOKEN_VERSION_CLAIM, 0) == current_token_version(user)


class VersionedRefreshToken(RefreshToken):
    @classmethod
    def for_user(cls, user, membership=None):
        """`membership`: the school (staff Profile or parent Guardian) the session acts as; by default where the
        person was last (accounts/memberships.py)."""
        from .memberships import MEMBERSHIP_CLAIM, default_for, key_of, remember

        token = super().for_user(user)
        token[TOKEN_VERSION_CLAIM] = current_token_version(user)
        membership = membership or default_for(user)
        if membership is not None:
            token[MEMBERSHIP_CLAIM] = key_of(membership)
            remember(user, membership)
        return token


def tokens_for(user, membership=None):
    """A fresh access/refresh pair for a user who just proved who they are."""
    refresh = VersionedRefreshToken.for_user(user, membership)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class VersionedTokenRefreshSerializer(TokenRefreshSerializer):
    """simplejwt's refresh (with rotation and blacklisting), refusing out-of-date tokens."""

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        user = get_user_model().objects.filter(
            **{api_settings.USER_ID_FIELD: refresh.payload.get(api_settings.USER_ID_CLAIM)}
        ).first()
        if user is None or not token_is_current(refresh, user):
            raise InvalidToken("This session has ended. Please sign in again.")
        from .memberships import MEMBERSHIP_CLAIM, default_for, key_of

        if MEMBERSHIP_CLAIM not in refresh.payload:
            # A session from before one login could have several schools: from now on its tokens name its school.
            membership = default_for(user)
            if membership is not None:
                refresh[MEMBERSHIP_CLAIM] = key_of(membership)
                attrs = {**attrs, "refresh": str(refresh)}
        return super().validate(attrs)
