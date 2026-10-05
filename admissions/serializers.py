from rest_framework import serializers

from students.models import YearGroup

from .models import AdmissionsSettings, Application

FAMILY_FIELDS = ["year_group", "start", "first_name", "last_name", "date_of_birth", "gender", "nationality",
                 "current_school", "mode_of_learning", "medical_notes", "notes", "parent_name", "parent_email",
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

    class Meta:
        model = Application
        fields = ["id", "reference", "status", "status_label", "year_group_name", *FAMILY_FIELDS, "staff_notes",
                  "interview_at", "decision_note", "decided_by_name", "student", "student_class", "created_at",
                  "updated_at"]
        read_only_fields = [f for f in FAMILY_FIELDS if f != "year_group"] + [
            "decided_by_name", "student", "created_at", "updated_at"]

    def get_fields(self):
        fields = super().get_fields()
        fields["year_group"].queryset = YearGroup.objects.filter(school=self.context["request"].user.profile.school)
        return fields

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
        fields = ["is_open", "intro", "year_groups", "link_token", "retention_days"]

    def get_fields(self):
        fields = super().get_fields()
        fields["year_groups"].child_relation.queryset = YearGroup.objects.filter(
            school=self.context["request"].user.profile.school)
        return fields
