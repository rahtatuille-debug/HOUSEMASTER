from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from .emails import send_password_reset_email
from .models import Invite, PasswordResetToken, Profile


class InviteSerializer(serializers.ModelSerializer):
    """Used by admins to create/list/manage invites for their own school."""

    invited_by_username = serializers.CharField(source="invited_by.username", read_only=True)
    accepted_by_username = serializers.CharField(
        source="accepted_by.username", read_only=True, default=None
    )
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Invite
        fields = [
            "id", "school", "role", "name", "email", "token",
            "invited_by_username", "created_at", "expires_at",
            "accepted_at", "accepted_by_username", "status",
        ]
        extra_kwargs = {
            "school": {"read_only": True},
            "token": {"read_only": True},
            "created_at": {"read_only": True},
            "accepted_at": {"read_only": True},
        }


class InvitePreviewSerializer(serializers.ModelSerializer):
    school_name = serializers.CharField(source="school.name", read_only=True)

    class Meta:
        model = Invite
        fields = ["school_name", "role", "status"]


class AcceptInviteSerializer(serializers.Serializer):
    token = serializers.CharField()
    username = serializers.CharField(max_length=150)
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
        self._invite = invite
        return value

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def save(self):
        invite = self._invite
        user = User.objects.create_user(
            username=self.validated_data["username"],
            password=self.validated_data["password"],
        )
        Profile.objects.create(user=user, school=invite.school, role=invite.role)
        invite.accepted_at = timezone.now()
        invite.accepted_by = user
        invite.save(update_fields=["accepted_at", "accepted_by"])
        return user


class RequestPasswordResetSerializer(serializers.Serializer):
    """
    Accepts a username (rather than an email — User.email isn't guaranteed
    to be populated for staff created via the invite flow). Always
    succeeds from the caller's point of view, whether or not the username
    exists, so this endpoint can't be used to probe which usernames are
    registered.
    """

    username = serializers.CharField()

    def save(self):
        try:
            user = User.objects.get(username=self.validated_data["username"], is_active=True)
        except User.DoesNotExist:
            return
        if not user.email:
            return
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