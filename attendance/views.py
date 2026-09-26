from rest_framework import viewsets

from accounts.mixins import SchoolScopedViewSetMixin
from activity.services import log_activity, student_name

from .models import AttendanceRecord
from .serializers import AttendanceRecordSerializer


class AttendanceRecordViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = AttendanceRecord.objects.all()
    serializer_class = AttendanceRecordSerializer
    filterset_fields = ["student", "date", "status"]
    school_lookup = "student__school"

    def perform_create(self, serializer):
        self.check_belongs_to_school(serializer.validated_data["student"].school, "student")
        record = serializer.save()
        log_activity(
            school=self.get_school(), actor=self.request.user, action="attendance.created", target=record,
            summary=f"Marked {student_name(record.student)} {record.status} on {record.date}",
            status=record.status,
        )

    def perform_update(self, serializer):
        student = serializer.validated_data.get("student", serializer.instance.student)
        self.check_belongs_to_school(student.school, "student")
        old = serializer.instance.status
        record = serializer.save()
        if old != record.status:
            log_activity(
                school=self.get_school(), actor=self.request.user, action="attendance.updated",
                target=record,
                summary=f"Changed {student_name(record.student)}'s attendance on {record.date} "
                f"from {old} to {record.status}",
                old=old, new=record.status,
            )

    def perform_destroy(self, instance):
        log_activity(
            school=self.get_school(), actor=self.request.user, action="attendance.deleted",
            target=instance,
            summary=f"Deleted {student_name(instance.student)}'s attendance record for {instance.date}",
            status=instance.status,
        )
        instance.delete()
