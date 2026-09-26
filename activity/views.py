from django.db.models import Q
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
    Filter with ?action=, ?actor=, ?target_type=, ?target_id=,
    ?since= / ?until= (YYYY-MM-DD, inclusive), and ?category=, a
    comma-separated list of action prefixes (e.g. "staff,staff_invite"
    matches "staff.deactivated" and "staff_invite.created").
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
        if category := params.get("category"):
            prefixes = [p.strip() for p in category.split(",") if p.strip()]
            match = Q()
            for prefix in prefixes:
                match |= Q(action__startswith=f"{prefix}.")
            queryset = queryset.filter(match)
        return queryset
