from rest_framework import viewsets

from accounts.mixins import SchoolScopedViewSetMixin

from .models import AttendanceRecord
from .serializers import AttendanceRecordSerializer


class AttendanceRecordViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = AttendanceRecord.objects.all()
    serializer_class = AttendanceRecordSerializer
    filterset_fields = ["student", "date", "status"]
    school_lookup = "student__school"

    def perform_create(self, serializer):
        self.check_belongs_to_school(serializer.validated_data["student"].school, "student")
        serializer.save()

    def perform_update(self, serializer):
        student = serializer.validated_data.get("student", serializer.instance.student)
        self.check_belongs_to_school(student.school, "student")
        serializer.save()
