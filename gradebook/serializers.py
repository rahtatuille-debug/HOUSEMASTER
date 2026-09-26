from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin
from .models import Subject, Term, Grade


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "school", "name"]
        extra_kwargs = {"school": {"read_only": True}}


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ["id", "school", "name", "start_date", "end_date", "is_locked", "locked_at"]
        extra_kwargs = {"school": {"read_only": True}, "is_locked": {"read_only": True},
                        "locked_at": {"read_only": True}}


class GradeSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Grade
        fields = ["id", "student", "subject", "term", "score", "max_score", "recorded_at"]