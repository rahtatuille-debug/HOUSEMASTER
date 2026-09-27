"""
Getting a new school going: a public sign-up that creates the school and
its first admin, and the setup wizard that admin completes before the school
starts using HouseMaster (education system, year groups and classes,
subjects, terms, grading and school details).
"""
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Profile, username_for_email
from accounts.permissions import HasSchoolProfile, IsSchoolAdmin
from activity.services import log_activity
from gradebook.levels import SCALES
from gradebook.models import Subject, Term

from .models import School, SchoolClass, YearGroup
from .presets import SYSTEMS, catalogue

MAX_PROGRESS_CHARS = 50_000


class RegistrationThrottle(SimpleRateThrottle):
    """Limits sign-ups per IP address, so the form can't be used to mass-create schools."""
    scope = "school_registration"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class RegisterSchoolSerializer(serializers.Serializer):
    school_name = serializers.CharField(min_length=2, max_length=255)
    name = serializers.CharField(min_length=2, max_length=255, help_text="The admin's full name.")
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    accept_privacy = serializers.BooleanField()

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists. Sign in instead.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_accept_privacy(self, value):
        if not value:
            raise serializers.ValidationError("Please read and accept the privacy notice to continue.")
        return value


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([RegistrationThrottle])
def register_school(request):
    """Create a new school and its first admin, and sign them in. The setup wizard comes next."""
    data = RegisterSchoolSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    name = " ".join(v["name"].split())
    first, _, last = name.partition(" ")
    with transaction.atomic():
        school = School.objects.create(name=" ".join(v["school_name"].split()))
        user = User.objects.create_user(username=username_for_email(v["email"]), email=v["email"],
                                        password=v["password"], first_name=first[:150], last_name=last[:150])
        Profile.objects.create(user=user, school=school, role=Profile.Role.ADMIN, display_name=name,
                               privacy_accepted_at=timezone.now())
        log_activity(school=school, actor=user, action="school.registered",
                     summary=f"{name} registered {school.name} on HouseMaster")
    refresh = RefreshToken.for_user(user)
    return Response({"access": str(refresh.access_token), "refresh": str(refresh)}, status=201)


def _school_state(school):
    return {
        "name": school.name, "motto": school.motto, "address": school.address, "phone": school.phone,
        "email": school.email, "privacy_contact": school.privacy_contact, "report_tone": school.report_tone,
        "grading_scale": school.grading_scale, "education_system": school.education_system,
        "setup_progress": school.setup_progress, "setup_completed_at": school.setup_completed_at,
    }


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def setup_state(request):
    """
    GET: the choices on offer and what the school already has. PATCH
    {"progress": {...}}: save the wizard's answers so far, so the admin can
    leave and pick up where they left off.
    """
    school = request.user.profile.school
    if request.method == "PATCH":
        progress = request.data.get("progress")
        if not isinstance(progress, dict) or len(str(progress)) > MAX_PROGRESS_CHARS:
            raise serializers.ValidationError({"progress": "Send the wizard's answers as an object."})
        school.setup_progress = progress
        school.save(update_fields=["setup_progress"])
    return Response({
        **catalogue(),
        "school": _school_state(school),
        "existing": {
            "year_groups": list(YearGroup.objects.filter(school=school).values_list("name", flat=True)),
            "classes": list(SchoolClass.objects.filter(year_group__school=school).values_list("name", flat=True)),
            "subjects": list(Subject.objects.filter(school=school).values_list("name", flat=True)),
            "terms": list(Term.objects.filter(school=school).values_list("name", flat=True)),
        },
    })


class _YearGroupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    classes = serializers.ListField(child=serializers.CharField(max_length=100), max_length=30)

    def validate_classes(self, value):
        names = [" ".join(v.split()) for v in value if v.strip()]
        if not names:
            raise serializers.ValidationError("Every year group needs at least one class.")
        if len({n.lower() for n in names}) != len(names):
            raise serializers.ValidationError("Class names in a year group must be different.")
        return names


class _TermSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs):
        if attrs["end_date"] <= attrs["start_date"]:
            raise serializers.ValidationError(f'{attrs["name"]} must end after it starts.')
        return attrs


class FinishSetupSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=255)
    motto = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    address = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    privacy_contact = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    education_system = serializers.ChoiceField(choices=list(SYSTEMS))
    year_groups = _YearGroupSerializer(many=True)
    subjects = serializers.ListField(child=serializers.CharField(max_length=100), max_length=200)
    terms = _TermSerializer(many=True)
    grading_scale = serializers.ChoiceField(choices=list(SCALES))
    report_tone = serializers.ChoiceField(choices=[c[0] for c in School._meta.get_field("report_tone").choices])

    def validate_year_groups(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one year group.")
        names = [" ".join(v["name"].split()).lower() for v in value]
        if len(set(names)) != len(names):
            raise serializers.ValidationError("Year group names must be different.")
        return value

    def validate_subjects(self, value):
        names = list(dict.fromkeys(" ".join(v.split()) for v in value if v.strip()))
        if not names:
            raise serializers.ValidationError("Choose at least one subject.")
        return names

    def validate_terms(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one term.")
        if len({t["name"].strip().lower() for t in value}) != len(value):
            raise serializers.ValidationError("Term names must be different.")
        return value


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def finish_setup(request):
    """
    Create everything chosen in the wizard and open the school for use.
    Anything that already exists with the same name is kept rather than
    duplicated, so finishing twice is harmless.
    """
    data = FinishSetupSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    school = request.user.profile.school
    created = {"year_groups": 0, "classes": 0, "subjects": 0, "terms": 0}
    with transaction.atomic():
        for field in ("motto", "address", "phone", "email", "privacy_contact", "education_system",
                      "grading_scale", "report_tone"):
            setattr(school, field, v[field].strip() if isinstance(v[field], str) else v[field])
        school.name = " ".join(v["name"].split())
        for group in v["year_groups"]:
            year_group, made = YearGroup.objects.get_or_create(school=school, name=" ".join(group["name"].split()))
            created["year_groups"] += made
            for class_name in group["classes"]:
                _, made = SchoolClass.objects.get_or_create(year_group=year_group, name=class_name)
                created["classes"] += made
        for subject in v["subjects"]:
            _, made = Subject.objects.get_or_create(school=school, name=subject)
            created["subjects"] += made
        for term in v["terms"]:
            _, made = Term.objects.get_or_create(
                school=school, name=" ".join(term["name"].split()),
                defaults={"start_date": term["start_date"], "end_date": term["end_date"]},
            )
            created["terms"] += made
        first_time = school.setup_completed_at is None
        school.setup_completed_at = school.setup_completed_at or timezone.now()
        school.setup_progress = {}
        school.save()
        log_activity(
            school=school, actor=request.user, action="school.setup_finished" if first_time else "school.setup_rerun",
            summary=f"{'Finished' if first_time else 'Re-ran'} school setup ({SYSTEMS[v['education_system']]['name']}): "
                    f"{created['year_groups']} year groups, {created['classes']} classes, "
                    f"{created['subjects']} subjects and {created['terms']} terms added",
            **created,
        )
    return Response({"school": _school_state(school), "created": created})
