from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin

from activity.services import display_name

from .models import StudentReport


class StudentReportSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
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
            "id", "student", "term", "progress_summary", "report_comment", "principal_comment", "extra", "extra_groups",
            "tone_used", "status", "review_note", "generated_at", "edited_at",
            "submitted_by_name", "submitted_at", "finalized_by_name", "finalized_at",
        ]
        read_only_fields = [
            "tone_used", "status", "review_note", "generated_at", "edited_at",
            "submitted_at", "finalized_at",
        ]

    extra_groups = serializers.SerializerMethodField()

    def get_extra_groups(self, obj):
        """The ratings this student's report card has (CBC competencies, IB approaches to learning)."""
        from gradebook.systems import REPORT_EXTRAS
        from students.presets import student_section

        return REPORT_EXTRAS.get(student_section(obj.student)[0], [])

    def validate_extra(self, value):
        from gradebook.systems import clean_extra
        from students.presets import student_section

        student = self.instance.student if self.instance else None
        system = student_section(student)[0] if student else self.context["request"].user.profile.school.education_system
        try:
            return clean_extra(system, value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))

    def get_submitted_by_name(self, obj):
        return display_name(obj.submitted_by) if obj.submitted_by else None

    def get_finalized_by_name(self, obj):
        return display_name(obj.finalized_by) if obj.finalized_by else None


class GenerateReportSerializer(serializers.Serializer):
    """Input for the generate-report action: which student/term to generate for."""
    student = serializers.IntegerField()
    term = serializers.IntegerField()
