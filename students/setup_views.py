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

from accounts.models import Profile, username_for_email
from accounts.permissions import HasSchoolProfile, IsSchoolAdmin
from accounts.throttles import RegistrationEmailThrottle
from accounts.tokens import tokens_for
from activity.services import log_activity
from gradebook.levels import SCALES
from gradebook.models import AssessmentType, Subject, Term

from .models import School, SchoolClass, YearGroup
from .presets import COUNTRIES, SYSTEMS, catalogue, subject_key

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
    country = serializers.ChoiceField(choices=list(COUNTRIES), required=False, default="ke")

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
@throttle_classes([RegistrationThrottle, RegistrationEmailThrottle])
def register_school(request):
    """Create a new school and its first admin, and sign them in. The setup wizard comes next."""
    data = RegisterSchoolSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    name = " ".join(v["name"].split())
    first, _, last = name.partition(" ")
    with transaction.atomic():
        school = School.objects.create(name=" ".join(v["school_name"].split()), country=v["country"])
        user = User.objects.create_user(username=username_for_email(v["email"]), email=v["email"],
                                        password=v["password"], first_name=first[:150], last_name=last[:150])
        Profile.objects.create(user=user, school=school, role=Profile.Role.ADMIN, display_name=name,
                               privacy_accepted_at=timezone.now())
        log_activity(school=school, actor=user, action="school.registered",
                     summary=f"{name} registered {school.name} on HouseMaster")
    return Response(tokens_for(user), status=201)


def setup_stage(school):
    """Where a school is in setup: "structure", then "people", then "done"."""
    if school.setup_completed_at:
        return "done"
    return "people" if school.structure_completed_at else "structure"


def _school_state(school):
    return {
        "name": school.name, "motto": school.motto, "address": school.address, "phone": school.phone,
        "email": school.email, "privacy_contact": school.privacy_contact, "report_tone": school.report_tone,
        "country": school.country,
        "grading_scale": school.grading_scale, "education_system": school.education_system,
        "setup_progress": school.setup_progress, "setup_completed_at": school.setup_completed_at,
        "setup_stage": setup_stage(school),
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


class _AssessmentSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60)
    weight = serializers.DecimalField(max_digits=5, decimal_places=1, min_value=0, max_value=100)


class FinishSetupSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=255)
    motto = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    address = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    privacy_contact = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    country = serializers.ChoiceField(choices=list(COUNTRIES), required=False, default="ke")
    education_system = serializers.ChoiceField(choices=list(SYSTEMS))
    year_groups = _YearGroupSerializer(many=True)
    subjects = serializers.ListField(child=serializers.CharField(max_length=100), max_length=200)
    terms = _TermSerializer(many=True)
    grading_scale = serializers.ChoiceField(choices=list(SCALES))
    assessments = _AssessmentSerializer(many=True, required=False, default=list)
    vocab_overrides = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False, default=dict)

    def validate_vocab_overrides(self, value):
        from .presets import clean_vocab_overrides

        try:
            return clean_vocab_overrides(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
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
    created = {"year_groups": 0, "classes": 0, "subjects": 0, "terms": 0, "assessment_types": 0}
    with transaction.atomic():
        for field in ("motto", "address", "phone", "email", "privacy_contact", "country", "education_system",
                      "grading_scale", "report_tone"):
            setattr(school, field, v[field].strip() if isinstance(v[field], str) else v[field])
        school.name = " ".join(v["name"].split())
        school.vocab_overrides = v["vocab_overrides"]
        last = len(v["year_groups"]) - 1
        for order, group in enumerate(v["year_groups"]):
            # In the order given, youngest first; the last is the final (graduating) year.
            year_group, made = YearGroup.objects.update_or_create(
                school=school, name=" ".join(group["name"].split()),
                defaults={"order": order, "is_final": order == last})
            created["year_groups"] += made
            for class_name in group["classes"]:
                _, made = SchoolClass.objects.get_or_create(year_group=year_group, name=class_name)
                created["classes"] += made
        for subject in v["subjects"]:
            _, made = Subject.objects.get_or_create(school=school, name=subject, education_system="")
            created["subjects"] += made
        for term in v["terms"]:
            _, made = Term.objects.get_or_create(
                school=school, name=" ".join(term["name"].split()),
                defaults={"start_date": term["start_date"], "end_date": term["end_date"]},
            )
            created["terms"] += made
        for order, item in enumerate(v["assessments"]):
            _, made = AssessmentType.objects.update_or_create(
                school=school, name=" ".join(item["name"].split()), defaults={"weight": item["weight"], "order": order})
            created["assessment_types"] += made
        first_time = school.setup_completed_at is None
        # A new school moves on to adding its people; it opens once they're in (see complete_setup).
        school.structure_completed_at = school.structure_completed_at or timezone.now()
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


class AddSectionSerializer(serializers.Serializer):
    education_system = serializers.ChoiceField(choices=list(SYSTEMS))
    grading_scale = serializers.ChoiceField(choices=list(SCALES), required=False, allow_blank=True, default="")
    year_groups = _YearGroupSerializer(many=True)
    subjects = serializers.ListField(child=serializers.CharField(max_length=100), max_length=200, required=False,
                                     default=list)

    def validate_year_groups(self, value):
        return FinishSetupSerializer.validate_year_groups(self, value)

    def validate_subjects(self, value):
        return list(dict.fromkeys(" ".join(v.split()) for v in value if v.strip()))


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def add_section(request):
    """
    Add a second curriculum to a school that already runs one (e.g. a CBC
    school with a British IGCSE section): new year groups that follow that
    system and grading scale, their classes, and any extra subjects. The
    section's year groups come after the school's existing ones, and the
    last of them is its graduating year.
    """
    data = AddSectionSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    school = request.user.profile.school
    system = v["education_system"]
    scale = v["grading_scale"] or SYSTEMS[system]["scales"][0]
    names = [" ".join(g["name"].split()) for g in v["year_groups"]]
    taken = set(YearGroup.objects.filter(school=school, name__in=names).values_list("name", flat=True))
    if taken:
        raise serializers.ValidationError({"year_groups": f"{', '.join(sorted(taken))} already exist. "
                                                          "Give the new section's year groups different names."})
    created = {"year_groups": 0, "classes": 0, "subjects": 0}
    with transaction.atomic():
        start = max(YearGroup.objects.filter(school=school).values_list("order", flat=True), default=-1) + 1
        last = len(names) - 1
        for i, (name, group) in enumerate(zip(names, v["year_groups"])):
            year_group = YearGroup.objects.create(
                school=school, name=name, order=start + i, is_final=i == last,
                # The school's own system needs no override.
                education_system="" if system == school.education_system else system,
                grading_scale="" if scale == school.grading_scale and system == school.education_system else scale,
            )
            created["year_groups"] += 1
            for class_name in group["classes"]:
                SchoolClass.objects.create(year_group=year_group, name=class_name)
                created["classes"] += 1
        for subject in v["subjects"]:
            # The section keeps its own subject list, separate from the rest of the school's.
            _, made = Subject.objects.get_or_create(school=school, name=subject,
                                                    education_system=subject_key(school, system))
            created["subjects"] += made
        log_activity(
            school=school, actor=request.user, action="school.section_added",
            summary=f"Added a {SYSTEMS[system]['name']} section: {created['year_groups']} year groups, "
                    f"{created['classes']} classes and {created['subjects']} new subjects",
            **created,
        )
    return Response({"created": created}, status=201)


class PreviewReportSerializer(serializers.Serializer):
    """The wizard's answers so far; only the education system is needed."""
    education_system = serializers.ChoiceField(choices=list(SYSTEMS))
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    motto = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    address = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    email = serializers.CharField(max_length=254, required=False, allow_blank=True, default="")
    country = serializers.ChoiceField(choices=list(COUNTRIES), required=False)
    grading_scale = serializers.ChoiceField(choices=list(SCALES), required=False)
    report_tone = serializers.ChoiceField(choices=[c[0] for c in School._meta.get_field("report_tone").choices],
                                          required=False)
    year_groups = _YearGroupSerializer(many=True, required=False)
    subjects = serializers.ListField(child=serializers.CharField(max_length=100), max_length=200, required=False)
    terms = _TermSerializer(many=True, required=False)
    vocab_overrides = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False)

    def validate_vocab_overrides(self, value):
        return FinishSetupSerializer.validate_vocab_overrides(self, value)


class PreviewThrottle(SimpleRateThrottle):
    scope = "report_preview"
    rate = "30/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
@throttle_classes([PreviewThrottle])
def preview_report_card(request):
    """A sample report card (PDF) for a made-up student, in the style chosen in the wizard so far. Nothing is saved."""
    from django.http import HttpResponse

    from reporting.preview import sample_report_pdf

    data = PreviewReportSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    pdf = sample_report_pdf(data.validated_data)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="sample-report-card.pdf"'
    return response


def people_status(school, admin=None):
    """What's in place for setup's people steps, and whether each required step is done."""
    from accounts.models import Invite, Profile
    from guardians.models import ClassSignupLink, Guardian, GuardianInvite

    staff = Profile.objects.filter(school=school).exclude(user=admin).count()
    staff_invites = Invite.objects.filter(school=school, accepted_at__isnull=True).count()
    students = school.students.filter(is_active=True).count()
    classes = SchoolClass.objects.filter(year_group__school=school).count()
    links = ClassSignupLink.objects.filter(school=school, is_active=True).count()
    parents = Guardian.objects.filter(school=school).count()
    parent_invites = GuardianInvite.objects.filter(school=school, accepted_at__isnull=True).count()
    return {
        "stage": setup_stage(school),
        "staff": {"accounts": staff, "invites": staff_invites, "done": staff + staff_invites > 0},
        "students": {"count": students, "done": students > 0},
        "parents": {"classes": classes, "links": links, "accounts": parents, "invites": parent_invites,
                    "done": links + parents + parent_invites > 0},
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def setup_people(request):
    """Progress through setup's people steps (staff, students, parents)."""
    return Response(people_status(request.user.profile.school, request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def complete_setup(request):
    """Open the school once its structure is set up and staff, students and parents have been added."""
    school = request.user.profile.school
    status = people_status(school, request.user)
    if status["stage"] == "structure":
        raise serializers.ValidationError("Finish setting up the school's classes, subjects and terms first.")
    missing = [what for key, what in (("staff", "invite at least one member of staff"),
                                      ("students", "add your students"),
                                      ("parents", "turn on a sign-up link or invite a parent"))
               if not status[key]["done"]]
    if missing:
        raise serializers.ValidationError(f"Before opening the school, {', '.join(missing)}.")
    if school.setup_completed_at is None:
        school.setup_completed_at = timezone.now()
        school.save(update_fields=["setup_completed_at"])
        log_activity(school=school, actor=request.user, action="school.setup_completed",
                     summary=f"Finished setup: {status['staff']['accounts'] + status['staff']['invites']} staff, "
                             f"{status['students']['count']} students and {status['parents']['links']} class sign-up "
                             f"links")
    return Response(people_status(school, request.user))
