from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin
from .models import School, YearGroup, SchoolClass, Student


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ["id", "name", "report_tone", "grading_scale", "privacy_contact", "education_system", "country", "vocab_overrides", "motto",
                  "address", "phone", "email", "created_at"]

    def validate_vocab_overrides(self, value):
        from .presets import clean_vocab_overrides

        try:
            return clean_vocab_overrides(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))


class YearGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = YearGroup
        fields = ["id", "school", "name", "order", "is_final", "education_system", "grading_scale"]
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
    class Meta:
        model = SchoolClass
        fields = ["id", "year_group", "name", "house"]


class StudentSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            "id", "school", "school_class", "external_id",
            "first_name", "last_name", "house", "enrolled_on", "is_active",
            "gender", "date_of_birth", "nationality", "mode_of_learning", "medical_notes",
            "has_photo", "photo_updated_at", "pathway", "subject_choices",
        ]
        extra_kwargs = {"school": {"read_only": True}, "photo_updated_at": {"read_only": True},
                        "pathway": {"read_only": True}}

    has_photo = serializers.SerializerMethodField()
    # Electives chosen and IB levels; changed through the class subject choices grid.
    subject_choices = serializers.SerializerMethodField()

    def get_subject_choices(self, obj):
        return [{"subject": c.subject_id, "level": c.level} for c in obj.subject_choices.all()]

    def get_has_photo(self, obj):
        return obj.photo_updated_at is not None