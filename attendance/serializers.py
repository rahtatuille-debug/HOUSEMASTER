from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin
from .models import AttendanceRecord


class AttendanceRecordSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = AttendanceRecord
        fields = ["id", "student", "date", "status", "notes"]
