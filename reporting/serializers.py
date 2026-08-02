from rest_framework import serializers
from .models import StudentReport


class StudentReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentReport
        fields = [
            "id", "student", "term", "progress_summary", "report_comment",
            "tone_used", "status", "generated_at", "edited_at",
        ]
        read_only_fields = ["tone_used", "generated_at", "edited_at"]


class GenerateReportSerializer(serializers.Serializer):
    """Input for the generate-report action: which student/term to generate for."""
    student = serializers.IntegerField()
    term = serializers.IntegerField()
