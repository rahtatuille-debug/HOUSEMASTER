from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .emails import send_password_reset_email
from .models import Invite, PasswordResetToken, Profile, username_for_email


class InviteSerializer(serializers.ModelSerializer):
    """Used by admins to create/list/manage invites for their own school."""

    invited_by_email = serializers.CharField(source="invited_by.email", read_only=True)
    accepted_by_email = serializers.CharField(
        source="accepted_by.email", read_only=True, default=None
    )
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Invite
        fields = [
            "id", "school", "role", "name", "email", "token",
            "invited_by_email", "created_at", "expires_at",
            "accepted_at", "accepted_by_email", "status",
        ]
        extra_kwargs = {
            "school": {"read_only": True},
            "token": {"read_only": True},
            "created_at": {"read_only": True},
            "accepted_at": {"read_only": True},
        }

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with that email already exists.")
        if Invite.objects.filter(email__iexact=value, accepted_at__isnull=True).exists():
            raise serializers.ValidationError("There's already a pending invite for that email.")
        return value

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("A staff member's name is required.")
        return name


class ProfileNameSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=255, trim_whitespace=True)

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Your name cannot be blank.")
        return name


class InvitePreviewSerializer(serializers.ModelSerializer):
    school_name = serializers.CharField(source="school.name", read_only=True)

    class Meta:
        model = Invite
        fields = ["school_name", "role", "email", "status"]


class AcceptInviteSerializer(serializers.Serializer):
    """
    The invitee only ever sets their own password — the account's email
    (and school and role) were already fixed by the admin when the invite
    was created, so there's nothing else to choose here.
    """

    token = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate_token(self, value):
        try:
            invite = Invite.objects.get(token=value)
        except Invite.DoesNotExist:
            raise serializers.ValidationError("This invite link is invalid.")
        if invite.is_accepted:
            raise serializers.ValidationError("This invite has already been used.")
        if invite.is_expired:
            raise serializers.ValidationError("This invite has expired. Ask your admin for a new one.")
        if not invite.email:
            raise serializers.ValidationError(
                "This invite is missing an email address — ask your admin to create a new one."
            )
        if User.objects.filter(email__iexact=invite.email).exists():
            raise serializers.ValidationError(
                "An account with this invite's email already exists. Ask your admin for help."
            )
        self._invite = invite
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def save(self):
        invite = self._invite
        display_name = invite.name.strip()
        first_name, _, last_name = display_name.partition(" ")
        user = User.objects.create_user(
            username=username_for_email(invite.email),
            email=invite.email,
            password=self.validated_data["password"],
            first_name=first_name[:150],
            last_name=last_name[:150],
        )
        Profile.objects.create(
            user=user,
            school=invite.school,
            role=invite.role,
            display_name=display_name,
        )
        invite.accepted_at = timezone.now()
        invite.accepted_by = user
        invite.save(update_fields=["accepted_at", "accepted_by"])
        return user


class RequestPasswordResetSerializer(serializers.Serializer):
    """
    Accepts an email address rather than a username. Always succeeds from
    the caller's point of view, whether or not that email is registered,
    so this endpoint can't be used to probe which accounts exist.

    Django's User model doesn't enforce email uniqueness, so more than one
    account can share an address — if so, every matching active account
    gets its own reset link in the same email round-trip, same as most
    real-world "forgot password" flows handle shared inboxes.
    """

    email = serializers.EmailField()

    def save(self):
        users = User.objects.filter(email__iexact=self.validated_data["email"], is_active=True)
        for user in users:
            reset_token = PasswordResetToken.objects.create(user=user)
            send_password_reset_email(reset_token)


class ConfirmPasswordResetSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate_token(self, value):
        try:
            reset_token = PasswordResetToken.objects.get(token=value)
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError("This reset link is invalid.")
        if reset_token.is_used:
            raise serializers.ValidationError("This reset link has already been used.")
        if reset_token.is_expired:
            raise serializers.ValidationError("This reset link has expired. Request a new one.")
        self._reset_token = reset_token
        return value

    def validate_password(self, value):
        validate_password(value, user=getattr(self, "_reset_token", None) and self._reset_token.user)
        return value

    def save(self):
        reset_token = self._reset_token
        user = reset_token.user
        user.set_password(self.validated_data["password"])
        user.save(update_fields=["password"])
        reset_token.used_at = timezone.now()
        reset_token.save(update_fields=["used_at"])
        return user


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Same as simplejwt's TokenObtainPairSerializer, but the login field is
    called `email` instead of `username` — matching accounts.auth_backends
    .EmailBackend, which is what actually does the authenticating.
    """

    username_field = "email"
