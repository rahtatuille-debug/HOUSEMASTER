from django.contrib.auth.models import User
from django.db import IntegrityError, models, transaction
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from activity.services import log_activity

from .emails import send_password_reset_email
from .mixins import SchoolScopedRelatedFieldsMixin, requester_school
from .models import Invite, PasswordResetToken, Profile, TeachingAssignment, username_for_email
from .tokens import VersionedRefreshToken


def email_in_use_at_school(email, school):
    """Whether a staff member or parent at this school already signs in with this email."""
    return User.objects.filter(email__iexact=email).filter(
        models.Q(profile__school=school) | models.Q(guardian__school=school)
    ).exists()


def create_account(field, message, **fields):
    """
    Create a User, turning a clash with an existing email (two sign-ups at
    the same moment, caught by the database's unique index) into the same
    friendly 400 as the check that runs first, rather than a 500.
    """
    try:
        with transaction.atomic():
            return User.objects.create_user(**fields)
    except IntegrityError:
        raise serializers.ValidationError({field: [message]})


def _log_for_user(user, action, what):
    """Log an event a user did to their own account, if they belong to a school."""
    owner = getattr(user, "profile", None) or getattr(user, "guardian", None)
    if owner is None:
        return
    log_activity(school=owner.school, actor=user, action=action, target=owner,
                 summary=f"{owner.name} {what}")


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
        # Only this school's accounts and invites are checked, so an admin
        # can't use this to find out whether an email is in use at another
        # school. If it is, accepting the invite fails instead, and only the
        # invitee (who owns that email) sees why.
        school = requester_school(self.context.get("request"))
        if email_in_use_at_school(value, school):
            raise serializers.ValidationError("Someone at your school already has an account with that email.")
        if Invite.objects.filter(school=school, email__iexact=value, accepted_at__isnull=True).exists():
            raise serializers.ValidationError("There's already a pending invite for that email.")
        return value

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("A staff member's name is required.")
        return name


class StaffMemberSerializer(serializers.ModelSerializer):
    """An admin's view of one staff member at their school."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)

    class Meta:
        model = Profile
        fields = ["id", "user_id", "name", "email", "role", "is_active", "date_joined", "last_login"]


class TeachingAssignmentSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.name", read_only=True)
    class_name = serializers.CharField(source="school_class.name", read_only=True)
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = TeachingAssignment
        fields = ["id", "teacher", "teacher_name", "school_class", "class_name", "subject", "subject_name"]
        validators = []  # duplicate check done in validate() with a readable message
        extra_kwargs = {"subject": {"required": False, "allow_null": True}}

    def get_subject_name(self, obj):
        if not obj.subject:
            return "All subjects"
        from students.presets import SHORT_NAMES

        system = obj.subject.education_system
        return f"{obj.subject.name} · {SHORT_NAMES.get(system, system)}" if system else obj.subject.name

    def validate(self, attrs):
        attrs.setdefault("subject", None)
        subject, school_class = attrs["subject"], attrs["school_class"]
        if subject is not None:
            from gradebook.choices import subject_system
            from students.presets import section_for

            school = school_class.year_group.school
            if subject_system(subject, school) != section_for(school_class.year_group, school)[0]:
                raise serializers.ValidationError(
                    f"{subject.name} belongs to a different curriculum from {school_class.name}.")
        if TeachingAssignment.objects.filter(
            teacher=attrs["teacher"], school_class=attrs["school_class"], subject=attrs["subject"]
        ).exists():
            raise serializers.ValidationError("This teacher is already assigned to that class and subject.")
        return attrs


class ProfileNameSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=255, trim_whitespace=True)

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Your name cannot be blank.")
        return name


class InvitePreviewSerializer(serializers.ModelSerializer):
    school_name = serializers.CharField(source="school.name", read_only=True)
    privacy_contact = serializers.CharField(source="school.privacy_contact", read_only=True)
    country = serializers.SerializerMethodField(read_only=True)

    def get_country(self, obj):
        from students.presets import country
        return country(obj.school.country)

    class Meta:
        model = Invite
        fields = ["school_name", "privacy_contact", "country", "role", "email", "status"]


class AcceptInviteSerializer(serializers.Serializer):
    """
    The invitee only ever sets their own password — the account's email
    (and school and role) were already fixed by the admin when the invite
    was created, so there's nothing else to choose here.
    """

    EMAIL_TAKEN = "An account with this invite's email already exists. Ask your admin for help."

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
            raise serializers.ValidationError(self.EMAIL_TAKEN)
        self._invite = invite
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def save(self):
        invite = self._invite
        display_name = invite.name.strip()
        first_name, _, last_name = display_name.partition(" ")
        user = create_account(
            "token", self.EMAIL_TAKEN,
            username=username_for_email(invite.email),
            email=invite.email,
            password=self.validated_data["password"],
            first_name=first_name[:150],
            last_name=last_name[:150],
        )
        profile = Profile.objects.create(
            user=user,
            school=invite.school,
            role=invite.role,
            display_name=display_name,
            privacy_accepted_at=timezone.now(),
        )
        # Classes chosen when the invite was made (e.g. from the staff import),
        # skipping any class or subject that has since been deleted.
        from gradebook.models import Subject
        from students.models import SchoolClass

        for item in invite.assignments or []:
            school_class = SchoolClass.objects.filter(
                pk=item.get("school_class"), year_group__school=invite.school).first()
            subject = Subject.objects.filter(pk=item.get("subject"), school=invite.school).first() \
                if item.get("subject") else None
            if school_class and (subject or not item.get("subject")):
                TeachingAssignment.objects.get_or_create(teacher=profile, school_class=school_class, subject=subject)
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
            _log_for_user(user, "password.reset_requested", "requested a password reset link")


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
        _log_for_user(user, "password.reset_completed", "reset their password")
        return user


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Same as simplejwt's TokenObtainPairSerializer, but the login field is
    called `email` instead of `username` — matching accounts.auth_backends
    .EmailBackend, which is what actually does the authenticating.
    """

    username_field = "email"
    # Tokens carry the account's session version (accounts/tokens.py).
    token_class = VersionedRefreshToken
