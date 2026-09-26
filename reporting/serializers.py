from rest_framework import serializers

from activity.services import display_name

from .models import StudentReport


class StudentReportSerializer(serializers.ModelSerializer):
    """
    `status` is read-only here: it only changes through the submit,
    finalize and send-back actions, so the approval step can't be skipped
    by editing it directly.
    """

    submitted_by_name = serializers.SerializerMethodField()
    finalized_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StudentReport
        fields = [
            "id", "student", "term", "progress_summary", "report_comment",
            "tone_used", "status", "review_note", "generated_at", "edited_at",
            "submitted_by_name", "submitted_at", "finalized_by_name", "finalized_at",
        ]
        read_only_fields = [
            "tone_used", "status", "review_note", "generated_at", "edited_at",
            "submitted_at", "finalized_at",
        ]

    def get_submitted_by_name(self, obj):
        return display_name(obj.submitted_by) if obj.submitted_by else None

    def get_finalized_by_name(self, obj):
        return display_name(obj.finalized_by) if obj.finalized_by else None


class GenerateReportSerializer(serializers.Serializer):
    """Input for the generate-report action: which student/term to generate for."""
    student = serializers.IntegerField()
    term = serializers.IntegerField()
