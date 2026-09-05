from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from .models import Invite, Profile


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