from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.permissions import HasSchoolProfile, IsSchoolAdmin

from .models import ActivityLog
from .serializers import ActivityLogSerializer


class ActivityPagination(PageNumberPagination):
    page_size = 50


class ActivityLogViewSet(SchoolScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Admin-only, read-only view of the school's activity log, newest first.
    Filter with ?action=, ?actor=, ?target_type=, ?target_id=, and
    ?since= / ?until= (YYYY-MM-DD, inclusive).
    """

    queryset = ActivityLog.objects.all()
    serializer_class = ActivityLogSerializer
    permission_classes = [HasSchoolProfile, IsSchoolAdmin]
    pagination_class = ActivityPagination
    filterset_fields = ["action", "actor", "target_type", "target_id"]

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if since := params.get("since"):
            queryset = queryset.filter(created_at__date__gte=since)
        if until := params.get("until"):
            queryset = queryset.filter(created_at__date__lte=until)
        return queryset
