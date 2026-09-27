from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin
from .models import School, YearGroup, SchoolClass, Student


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = ["id", "name", "report_tone", "grading_scale", "created_at"]


class YearGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = YearGroup
        fields = ["id", "school", "name"]
        extra_kwargs = {"school": {"read_only": True}}


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
            "has_photo", "photo_updated_at",
        ]
        extra_kwargs = {"school": {"read_only": True}, "photo_updated_at": {"read_only": True}}

    has_photo = serializers.SerializerMethodField()

    def get_has_photo(self, obj):
        return obj.photo_updated_at is not None