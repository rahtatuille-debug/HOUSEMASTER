from rest_framework import serializers

from accounts.models import Profile
from students.models import Student

from .models import Absence, BoardingHouse, Dorm, LeaveRequest, RollCall, SickBayVisit


def _student_name(student):
    return f"{student.first_name} {student.last_name}" if student else ""


class BoardingHouseSerializer(serializers.ModelSerializer):
    staff = serializers.PrimaryKeyRelatedField(many=True, queryset=Profile.objects.none(), required=False)
    staff_names = serializers.SerializerMethodField()
    dorms = serializers.SerializerMethodField()

    class Meta:
        model = BoardingHouse
        fields = ["id", "name", "staff", "staff_names", "dorms", "is_archived"]
        read_only_fields = ["is_archived"]

    def get_fields(self):
        fields = super().get_fields()
        fields["staff"].child_relation.queryset = Profile.objects.filter(
            school=self.context["request"].user.profile.school, user__is_active=True)
        return fields

    def get_staff_names(self, obj):
        return [p.name for p in obj.staff.all()]

    def get_dorms(self, obj):
        def holder(bed):
            # Someone who has left, or no longer boards, doesn't hold the bed (old data from before beds were freed).
            s = bed.student
            return s if s is not None and s.is_active and s.mode_of_learning == "boarding" else None

        return [{"id": d.id, "name": d.name, "beds": [
            {"id": b.id, "name": b.name, "student": holder(b).id if holder(b) else None,
             "student_name": _student_name(holder(b))} for b in d.beds.select_related("student")]}
            for d in obj.dorms.all()]


class DormSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dorm
        fields = ["id", "house", "name"]

    def get_fields(self):
        fields = super().get_fields()
        fields["house"].queryset = BoardingHouse.objects.filter(school=self.context["request"].user.profile.school)
        return fields


class LeaveRequestSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    house = serializers.SerializerMethodField()
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = ["id", "student", "student_name", "house", "kind", "kind_label", "leaving_at", "returning_at",
                  "reason", "collected_by", "status", "status_label", "requested_by_name", "requested_at",
                  "decided_by_name", "decided_at", "decision_note", "signed_out_at", "signed_out_by_name",
                  "signed_in_at", "signed_in_by_name"]
        read_only_fields = ["status", "requested_by_name", "requested_at", "decided_by_name", "decided_at",
                            "decision_note", "signed_out_at", "signed_out_by_name", "signed_in_at",
                            "signed_in_by_name"]

    def get_student_name(self, obj):
        return _student_name(obj.student)

    def get_house(self, obj):
        bed = getattr(obj.student, "bed", None)
        return bed.dorm.house.name if bed else ""

    def validate(self, data):
        leaving = data.get("leaving_at", getattr(self.instance, "leaving_at", None))
        returning = data.get("returning_at", getattr(self.instance, "returning_at", None))
        if leaving and returning and returning <= leaving:
            raise serializers.ValidationError({"returning_at": ["The return must be after leaving."]})
        return data


class SickBayVisitSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    outcome_label = serializers.CharField(source="get_outcome_display", read_only=True)

    class Meta:
        model = SickBayVisit
        fields = ["id", "student", "student_name", "checked_in_at", "checked_in_by_name", "complaint", "treatment",
                  "checked_out_at", "checked_out_by_name", "outcome", "outcome_label", "parents_told_at",
                  "parents_told_how"]
        read_only_fields = ["checked_in_by_name", "checked_out_at", "checked_out_by_name", "parents_told_at"]
        extra_kwargs = {"checked_in_at": {"required": False}}

    def get_student_name(self, obj):
        return _student_name(obj.student)


class RollCallSerializer(serializers.ModelSerializer):
    house_name = serializers.CharField(source="house.name", read_only=True)
    session_label = serializers.CharField(source="get_session_display", read_only=True)
    entries = serializers.SerializerMethodField()
    counts = serializers.SerializerMethodField()
    amendments = serializers.SerializerMethodField()

    class Meta:
        model = RollCall
        fields = ["id", "house", "house_name", "date", "session", "session_label", "taken_by_name", "created_at",
                  "completed_at", "entries", "counts", "amendments"]

    def get_amendments(self, obj):
        return [{"by": a.amended_by_name, "at": a.amended_at, "reason": a.reason, "changes": a.changes}
                for a in obj.amendments.all()]

    def get_entries(self, obj):
        rows = obj.entries.select_related("student__bed__dorm").order_by("student__bed__dorm__name",
                                                                         "student__last_name", "student__first_name")
        return [{"student": e.student_id, "name": _student_name(e.student),
                 "dorm": e.student.bed.dorm.name if hasattr(e.student, "bed") and e.student.bed else "",
                 "status": e.status, "note": e.note} for e in rows]

    def get_counts(self, obj):
        counts = {}
        for status in obj.entries.values_list("status", flat=True):
            counts[status or "unmarked"] = counts.get(status or "unmarked", 0) + 1
        return counts


def boarder_row(student, away):
    bed = student.bed
    return {"id": student.id, "name": _student_name(student),
            "class_name": student.school_class.name if student.school_class else "",
            "house": bed.dorm.house.name, "house_id": bed.dorm.house_id, "dorm": bed.dorm.name, "bed": bed.name,
            "where": away.get(student.id, "in")}


def bed_student_queryset(user):
    return Student.objects.filter(school=user.profile.school, is_active=True)


class AbsenceSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    house_name = serializers.CharField(source="house.name", read_only=True)
    resolution_label = serializers.CharField(source="get_resolution_display", read_only=True)
    since = serializers.DateTimeField(source="opened_at", read_only=True)

    class Meta:
        model = Absence
        fields = ["id", "student", "name", "house", "house_name", "roll_call", "status", "since", "note",
                  "resolution", "resolution_label", "resolved_at", "resolved_by_name", "resolution_note"]
        read_only_fields = fields

    def get_name(self, obj):
        return _student_name(obj.student)
