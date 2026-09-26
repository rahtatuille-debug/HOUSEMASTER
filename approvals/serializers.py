from rest_framework import serializers

from .models import ChangeRequest


class ChangeRequestSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ChangeRequest
        fields = [
            "id", "kind", "operation", "target_id", "data", "summary", "reason",
            "status", "status_label", "requested_by", "requested_by_name", "created_at",
            "reviewed_by_name", "reviewed_at", "review_note",
        ]
        read_only_fields = fields
