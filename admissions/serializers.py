import re

from rest_framework import serializers

from students.models import YearGroup

from .models import AdmissionsSettings, Application

# Older than this is almost certainly a typing mistake in the year (schools up to sixth form and gap years).
OLDEST_APPLICANT = 25

FAMILY_FIELDS = ["year_group", "start", "first_name", "last_name", "date_of_birth", "gender", "nationality",
                 "current_school", "mode_of_learning", "has_needs", "notes", "parent_name", "parent_email",
                 "parent_phone", "relationship"]


class ApplyForm(serializers.ModelSerializer):
    """What a family fills in on the public form."""

    consent = serializers.BooleanField(write_only=True)
    website = serializers.CharField(write_only=True, required=False, allow_blank=True)  # left empty by people

    class Meta:
        model = Application
        fields = FAMILY_FIELDS + ["consent", "website"]
        extra_kwargs = {"date_of_birth": {"required": True, "allow_null": False},
                        "parent_phone": {"required": True, "allow_blank": False}}

    def __init__(self, *args, settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings
        allowed = settings.year_groups.all() if settings and settings.year_groups.exists() else \
            YearGroup.objects.filter(school=settings.school) if settings else YearGroup.objects.none()
        self.fields["year_group"].queryset = allowed
        self.fields["year_group"].required = allowed.exists()
        self.fields["year_group"].allow_null = not allowed.exists()

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError("Please read and accept the privacy notice.")
        return value

    def validate_mode_of_learning(self, value):
        if value and value not in ("day", "boarding"):
            raise serializers.ValidationError("Choose day or boarding.")
        if value == "boarding" and self.settings and not self.settings.school.has_boarding:
            raise serializers.ValidationError("This school doesn't take boarders.")
        return value

    def validate_gender(self, value):
        if value and value not in ("female", "male", "other"):
            raise serializers.ValidationError("Choose female, male or other.")
        return value

    def validate_date_of_birth(self, value):
        from django.utils import timezone

        today = timezone.localdate()
        if value > today:
            raise serializers.ValidationError("The date of birth is in the future. Please check it.")
        if value.year < today.year - OLDEST_APPLICANT:
            raise serializers.ValidationError("Please check the date of birth: that would make the child over "
                                              f"{OLDEST_APPLICANT}.")
        return value

    def validate_parent_phone(self, value):
        # Lenient: Kenyan (0712 345 678, +254 712 345 678) and international numbers, with spaces, dashes,
        # dots or brackets. Only an obviously wrong number is refused.
        value = value.strip()
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"\+?[\d\s().-]+", value) or not 7 <= len(digits) <= 15:
            raise serializers.ValidationError("Enter a phone number, e.g. 0712 345 678 or +254 712 345 678.")
        return value

    def create(self, validated):
        validated.pop("consent", None)
        validated.pop("website", None)
        return super().create(validated)


class ApplicationSerializer(serializers.ModelSerializer):
    """Staff view: everything, plus what staff can change."""

    reference = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    year_group_name = serializers.CharField(source="year_group.name", read_only=True, default="")
    student_class = serializers.SerializerMethodField()
    student_number = serializers.SerializerMethodField()
    age_note = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = ["id", "reference", "status", "status_label", "year_group_name", *FAMILY_FIELDS, "medical_notes",
                  "staff_notes",
                  "interview_at", "decision_note", "decided_by_name", "student", "student_class", "student_number",
                  "age_note", "created_at", "updated_at"]
        read_only_fields = [f for f in FAMILY_FIELDS if f != "year_group"] + ["medical_notes",
            "decided_by_name", "student", "created_at", "updated_at"]

    def get_fields(self):
        fields = super().get_fields()
        fields["year_group"].queryset = YearGroup.objects.filter(school=self.context["request"].user.profile.school)
        return fields

    def get_student_number(self, obj):
        return obj.student.external_id if obj.student else ""

    def get_age_note(self, obj):
        """A note (never a block) when the child's age is two or more years from most of the year group."""
        from .services import typical_age, years_old

        if obj.date_of_birth is None or obj.year_group_id is None:
            return ""
        cache = self.context.setdefault("typical_ages", {})
        if obj.year_group_id not in cache:
            cache[obj.year_group_id] = typical_age(obj.year_group)
        typical = cache[obj.year_group_id]
        age = years_old(obj.date_of_birth)
        if typical is None or abs(age - typical) < 2:
            return ""
        return f"{obj.first_name} is {age}; most students in {obj.year_group.name} are {typical}. Check the year group."

    def get_student_class(self, obj):
        return obj.student.school_class.name if obj.student and obj.student.school_class else ""

    def validate_status(self, value):
        if value == Application.Status.ENROLLED:
            raise serializers.ValidationError("Use Enrol to enrol an applicant in a class.")
        if self.instance and self.instance.status == Application.Status.ENROLLED:
            raise serializers.ValidationError("This applicant is already enrolled.")
        return value


class SettingsSerializer(serializers.ModelSerializer):
    link_token = serializers.CharField(source="token", read_only=True)

    class Meta:
        model = AdmissionsSettings
        fields = ["is_open", "intro", "year_groups", "link_token", "retention_days", "number_prefix", "next_number"]

    def get_fields(self):
        fields = super().get_fields()
        fields["year_groups"].child_relation.queryset = YearGroup.objects.filter(
            school=self.context["request"].user.profile.school)
        return fields
