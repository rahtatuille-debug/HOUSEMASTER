from rest_framework import serializers

from activity.services import student_name

from .models import SupportConcern


class SupportConcernSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()
    term_name = serializers.CharField(source="term.name", read_only=True, default=None)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SupportConcern
        fields = [
            "id", "student", "student_name", "class_name", "term", "term_name", "status", "status_label", "source",
            "reasons", "note", "support_plan", "review_date", "created_by_name", "created_at",
            "updated_at", "closed_by_name", "closed_at", "closing_note", "parents_notified_at",
        ]
        read_only_fields = ["status", "source", "reasons", "created_by_name", "created_at", "updated_at",
                            "closed_by_name", "closed_at", "closing_note", "parents_notified_at"]
        extra_kwargs = {"note": {"max_length": 2000}, "support_plan": {"max_length": 4000}}

    def get_student_name(self, obj):
        return student_name(obj.student)

    def get_class_name(self, obj):
        klass = obj.student.school_class
        return f"{klass.year_group.name} — {klass.name}" if klass else None
