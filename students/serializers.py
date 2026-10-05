from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin
from .models import School, YearGroup, SchoolClass, Student


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ["id", "name", "report_tone", "grading_scale", "privacy_contact", "education_system", "country", "vocab_overrides", "motto",
                  "address", "phone", "email", "timezone", "support_pass_mark", "support_drop_points",
                  "support_attendance_min", "support_min_marks", "support_min_days", "support_reopen_points", "ranking_min_share", "has_boarding", "created_at"]

    def validate_timezone(self, value):
        from .localtime import valid_zones

        if value not in valid_zones():
            raise serializers.ValidationError('Choose a time zone from the list, e.g. "Africa/Nairobi".')
        return value

    def validate_vocab_overrides(self, value):
        from .presets import clean_vocab_overrides

        try:
            return clean_vocab_overrides(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))


class YearGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = YearGroup
        fields = ["id", "school", "name", "order", "is_final", "education_system", "grading_scale", "support_pass_mark"]
        extra_kwargs = {"school": {"read_only": True}}

    def validate_education_system(self, value):
        from .presets import SYSTEMS

        if value and value not in SYSTEMS:
            raise serializers.ValidationError("Choose one of the education systems.")
        return value

    def validate_grading_scale(self, value):
        from gradebook.levels import SCALES

        if value and value not in SCALES:
            raise serializers.ValidationError("Choose one of the grading scales.")
        return value


class SchoolClassSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    # The curriculum the class follows (its year group's, or the school's).
    section = serializers.SerializerMethodField()

    class Meta:
        model = SchoolClass
        fields = ["id", "year_group", "name", "house", "section"]

    def get_section(self, obj):
        return obj.year_group.education_system or obj.year_group.school.education_system


class StudentSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            "id", "school", "school_class", "external_id",
            "first_name", "last_name", "house", "enrolled_on", "is_active",
            "gender", "date_of_birth", "nationality", "mode_of_learning", "medical_notes",
            "has_photo", "photo_updated_at", "pathway", "subject_choices", "section", "scale", "needs_support",
        ]
        extra_kwargs = {"school": {"read_only": True}, "photo_updated_at": {"read_only": True},
                        "pathway": {"read_only": True}}
        # DRF would turn the per-school admission number constraint into a validator that makes external_id
        # required; validate_external_id checks it instead (blank stays allowed).
        validators = []

    has_photo = serializers.SerializerMethodField()
    # Marked by a teacher as needing support (support app); staff only.
    needs_support = serializers.SerializerMethodField()

    def validate_external_id(self, value):
        # Admission numbers are unique per school (a database constraint); say so instead of failing.
        value = value.strip()
        school = self.instance.school if self.instance else getattr(self.context.get("request"), "user", None) \
            and self.context["request"].user.profile.school
        if value and school is not None:
            taken = Student.objects.filter(school=school, external_id=value)
            if self.instance is not None:
                taken = taken.exclude(pk=self.instance.pk)
            if taken.exists():
                raise serializers.ValidationError("Another student already has this admission number.")
        return value

    def get_needs_support(self, obj):
        flagged = getattr(obj, "needs_support", None)  # annotated by StudentViewSet
        if flagged is None:
            flagged = obj.support_concerns.filter(status="open").exists()
        return bool(flagged)

    # Electives chosen and IB levels; changed through the class subject choices grid.
    subject_choices = serializers.SerializerMethodField()

    # The curriculum and grading scale of the student's section (the school's, unless their year group differs).
    section = serializers.SerializerMethodField()
    scale = serializers.SerializerMethodField()

    def get_subject_choices(self, obj):
        return [{"subject": c.subject_id, "level": c.level} for c in obj.subject_choices.all()]

    def get_section(self, obj):
        from .presets import student_section

        return student_section(obj)[0]

    def get_scale(self, obj):
        from .presets import student_section

        return student_section(obj)[1]

    def get_has_photo(self, obj):
        return obj.photo_updated_at is not None