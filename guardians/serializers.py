from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from accounts.models import username_for_email
from students.models import Student

from .models import Guardian, GuardianInvite


class GuardianInviteSerializer(serializers.ModelSerializer):
    invited_by_email = serializers.CharField(source="invited_by.email", read_only=True)
    accepted_by_email = serializers.CharField(
        source="accepted_by.email", read_only=True, default=None
    )
    status = serializers.CharField(read_only=True)
    student_names = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = GuardianInvite
        fields = [
            "id", "school", "name", "email", "students", "student_names", "token",
            "invited_by_email", "created_at", "expires_at",
            "accepted_at", "accepted_by_email", "status",
        ]
        extra_kwargs = {
            "school": {"read_only": True},
            "token": {"read_only": True},
            "created_at": {"read_only": True},
            "accepted_at": {"read_only": True},
        }

    def get_student_names(self, obj):
        return [f"{s.first_name} {s.last_name}" for s in obj.students.all()]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with that email already exists.")
        if GuardianInvite.objects.filter(email__iexact=value, accepted_at__isnull=True).exists():
            raise serializers.ValidationError("There's already a pending guardian invite for that email.")
        return value

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("A guardian's name is required.")
        return name

    def validate_students(self, value):
        if not value:
            raise serializers.ValidationError("Select at least one student.")
        return value


class GuardianInvitePreviewSerializer(serializers.ModelSerializer):
    school_name = serializers.CharField(source="school.name", read_only=True)
    student_names = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = GuardianInvite
        fields = ["school_name", "email", "student_names", "status"]

    def get_student_names(self, obj):
        return [f"{s.first_name} {s.last_name}" for s in obj.students.all()]


class AcceptGuardianInviteSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate_token(self, value):
        try:
            invite = GuardianInvite.objects.get(token=value)
        except GuardianInvite.DoesNotExist:
            raise serializers.ValidationError("This invite link is invalid.")
        if invite.is_accepted:
            raise serializers.ValidationError("This invite has already been used.")
        if invite.is_expired:
            raise serializers.ValidationError("This invite has expired. Ask the school for a new one.")
        if User.objects.filter(email__iexact=invite.email).exists():
            raise serializers.ValidationError(
                "An account with this invite's email already exists. Contact the school for help."
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
        guardian = Guardian.objects.create(
            user=user, school=invite.school, display_name=display_name,
        )
        guardian.students.set(invite.students.all())
        invite.accepted_at = timezone.now()
        invite.accepted_by = user
        invite.save(update_fields=["accepted_at", "accepted_by"])
        return user


class GuardianStudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = ["id", "first_name", "last_name", "school_class"]


class GuardianNameSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=255, trim_whitespace=True)

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Your name cannot be blank.")
        return name
