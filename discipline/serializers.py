from rest_framework import serializers

from activity.services import student_name

from .models import DisciplineIncident, Merit


class DisciplineIncidentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    severity_label = serializers.CharField(source="get_severity_display", read_only=True)
    action_label = serializers.CharField(source="get_action_display", read_only=True)
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = DisciplineIncident
        fields = [
            "id", "student", "student_name", "class_name", "date", "category", "category_label", "severity",
            "severity_label", "description", "action", "action_label", "action_detail", "staff_notes",
            "shared_with_parents", "parents_notified_at", "recorded_by_name", "created_at", "updated_at", "can_edit",
        ]
        read_only_fields = ["student", "parents_notified_at", "recorded_by_name", "created_at", "updated_at"]
        extra_kwargs = {"description": {"max_length": 4000}, "staff_notes": {"max_length": 4000}}

    def get_can_edit(self, obj):
        """The person who recorded it, leadership or an admin may change it."""
        from accounts.scoping import is_leader

        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(user and (obj.recorded_by_id == user.id or is_leader(user)))

    def get_student_name(self, obj):
        return student_name(obj.student)

    def get_class_name(self, obj):
        klass = obj.student.school_class
        return klass.name if klass else None

    def validate_description(self, value):
        if not value.strip():
            raise serializers.ValidationError("Say what happened.")
        return value.strip()


def parent_rows(student):
    """What a parent sees: shared records only, without the staff notes."""
    return [{
        "id": i.id, "date": i.date, "category_label": i.get_category_display(),
        "severity": i.severity, "severity_label": i.get_severity_display(), "description": i.description,
        "action_label": i.get_action_display(), "action_detail": i.action_detail,
        "recorded_by_name": i.recorded_by_name,
    } for i in student.discipline_incidents.filter(shared_with_parents=True)]


class MeritSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Merit
        fields = ["id", "student", "student_name", "class_name", "date", "category", "category_label", "points",
                  "reason", "shared_with_parents", "awarded_by_name", "created_at", "updated_at", "can_edit"]
        read_only_fields = ["student", "awarded_by_name", "created_at", "updated_at"]

    def get_can_edit(self, obj):
        """The person who gave it, leadership or an admin may change or remove it."""
        from accounts.scoping import is_leader

        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(user and (obj.awarded_by_id == user.id or is_leader(user)))

    def get_student_name(self, obj):
        return student_name(obj.student)

    def get_class_name(self, obj):
        klass = obj.student.school_class
        return klass.name if klass else None

    def validate_points(self, value):
        if not 1 <= value <= Merit.MAX_POINTS:
            raise serializers.ValidationError(f"Give between 1 and {Merit.MAX_POINTS} points.")
        return value

    def validate_reason(self, value):
        return value.strip()


def parent_merit_rows(student):
    """What a parent sees: shared merits, newest first."""
    return [{
        "id": m.id, "date": m.date, "category_label": m.get_category_display(), "points": m.points,
        "reason": m.reason, "awarded_by_name": m.awarded_by_name,
    } for m in student.merits.filter(shared_with_parents=True)]
