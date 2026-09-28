from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin
from .dates import attendance_date_problem
from .models import AttendanceRecord


class AttendanceRecordSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = AttendanceRecord
        fields = ["id", "student", "date", "status", "notes"]

    def validate(self, attrs):
        student = attrs.get("student", self.instance.student if self.instance else None)
        day = attrs.get("date")
        if student is not None and day is not None:
            problem = attendance_date_problem(student.school, day)
            if problem:
                raise serializers.ValidationError({"date": problem})
        return attrs
