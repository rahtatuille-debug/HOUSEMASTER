from rest_framework import serializers

from accounts.mixins import SchoolScopedRelatedFieldsMixin

from .models import ActivityLog


class ActivityLogSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = ActivityLog
        fields = [
            "id", "actor", "actor_name", "action", "summary",
            "target_type", "target_id", "details", "created_at",
        ]
