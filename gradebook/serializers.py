from rest_framework import serializers
from .models import Subject, Term, Grade


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "school", "name"]


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ["id", "school", "name", "start_date", "end_date"]


class GradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Grade
        fields = ["id", "student", "subject", "term", "score", "max_score", "recorded_at"]
