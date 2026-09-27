from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin
from .models import AssessmentType, Subject, Term, Grade


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "school", "name", "credits", "is_elective"]
        extra_kwargs = {"school": {"read_only": True}}


class AssessmentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentType
        fields = ["id", "school", "name", "weight", "order"]
        extra_kwargs = {"school": {"read_only": True}}

    def validate_weight(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("A weight is a percentage from 0 to 100.")
        return value


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ["id", "school", "name", "start_date", "end_date", "is_locked", "locked_at"]
        extra_kwargs = {"school": {"read_only": True}, "is_locked": {"read_only": True},
                        "locked_at": {"read_only": True}}


class GradeSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Grade
        fields = ["id", "student", "subject", "term", "score", "max_score", "assessment_type", "recorded_at"]