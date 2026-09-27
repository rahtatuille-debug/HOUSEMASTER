import re

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin

from accounts.models import username_for_email
from students.models import Student
from gradebook.models import Grade
from reporting.models import StudentReport

from .models import Guardian, GuardianInvite


class GuardianInviteSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
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
        # Same rule as staff invites: only this school is checked, so this
        # can't reveal accounts at other schools. See accounts.serializers.
        from accounts.mixins import requester_school
        from accounts.serializers import email_in_use_at_school

        school = requester_school(self.context.get("request"))
        if email_in_use_at_school(value, school):
            raise serializers.ValidationError("Someone at your school already has an account with that email.")
        if GuardianInvite.objects.filter(school=school, email__iexact=value, accepted_at__isnull=True).exists():
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
    privacy_contact = serializers.CharField(source="school.privacy_contact", read_only=True)
    student_names = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = GuardianInvite
        fields = ["school_name", "privacy_contact", "email", "student_names", "status"]

    def get_student_names(self, obj):
        return [f"{s.first_name} {s.last_name}" for s in obj.students.all()]


class AcceptGuardianInviteSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)
    accept_privacy = serializers.BooleanField(
        help_text="They've read the school's privacy notice and agree to it (Kenya Data Protection Act).",
    )

    def validate_accept_privacy(self, value):
        if not value:
            raise serializers.ValidationError("Please read and accept the privacy notice to continue.")
        return value

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
            user=user, school=invite.school, display_name=display_name, privacy_accepted_at=timezone.now(),
        )
        guardian.students.set(invite.students.all())
        invite.accepted_at = timezone.now()
        invite.accepted_by = user
        invite.save(update_fields=["accepted_at", "accepted_by"])
        return user


class GuardianStudentSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    school_class_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Student
        fields = [
            "id", "first_name", "last_name", "school_class", "school_class_name",
            "house", "enrolled_on", "is_active", "external_id", "gender", "date_of_birth",
            "nationality", "mode_of_learning", "medical_notes", "has_photo",
        ]

    has_photo = serializers.SerializerMethodField(read_only=True)

    def get_has_photo(self, obj):
        return obj.photo_updated_at is not None

    def get_school_class_name(self, obj):
        if not obj.school_class:
            return None
        return f"{obj.school_class.year_group.name} — {obj.school_class.name}"


class GuardianGradeSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    term_name = serializers.CharField(source="term.name", read_only=True)

    class Meta:
        model = Grade
        fields = ["id", "subject", "subject_name", "term", "term_name", "score", "max_score", "recorded_at"]


class GuardianReportSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    term_name = serializers.CharField(source="term.name", read_only=True)

    class Meta:
        model = StudentReport
        fields = [
            # The progress summary is written for staff records, so parents
            # only get the report comment.
            "id", "term", "term_name", "report_comment",
            "status", "generated_at", "edited_at", "finalized_at",
        ]


class GuardianNameSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=255, trim_whitespace=True)

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Your name cannot be blank.")
        return name


CONTACT_FIELDS = ["phone", "phone_alt", "relationship", "address", "occupation", "preferred_contact"]
PHONE_RE = re.compile(r"^\+?[0-9 ()\-]{7,25}$")


def _clean_phone(value):
    value = " ".join(value.split())
    if value and (not PHONE_RE.match(value) or sum(c.isdigit() for c in value) < 7):
        raise serializers.ValidationError("Enter a phone number, e.g. +254 712 345 678.")
    return value


class GuardianContactSerializer(serializers.ModelSerializer):
    """The contact details a parent can see and change themselves."""

    class Meta:
        model = Guardian
        fields = CONTACT_FIELDS + ["email_notifications"]

    def validate_phone(self, value):
        return _clean_phone(value)

    def validate_phone_alt(self, value):
        return _clean_phone(value)


class ParentSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    """An admin's view of one parent account, including which children it's linked to."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    student_names = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Guardian
        fields = [
            "id", "user_id", "name", "email", "is_active", "students", "student_names",
            "date_joined", "last_login", *CONTACT_FIELDS, "admin_note", "email_notifications",
        ]
        read_only_fields = ["email_notifications"]  # the parent's own choice

    def validate_phone(self, value):
        return _clean_phone(value)

    def validate_phone_alt(self, value):
        return _clean_phone(value)

    def get_student_names(self, obj):
        return [f"{s.first_name} {s.last_name}" for s in obj.students.all()]
