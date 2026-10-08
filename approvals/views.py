from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.scoping import is_admin, is_leader
from activity.services import log_activity
from housemaster.pagination import PagedOnRequest

from . import services
from .models import ChangeRequest
from .serializers import ChangeRequestSerializer


class ChangeRequestViewSet(SchoolScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Changes teachers have asked for. Admins and leadership see every
    request at their school and can approve or reject pending ones (with an
    optional `note`); changes to the school's own settings stay with admins. Teachers see only their own requests and can cancel pending
    ones. Requests are created by the viewsets that need approval, never
    through this endpoint. Filter with ?status=pending.
    """

    queryset = ChangeRequest.objects.all()
    serializer_class = ChangeRequestSerializer
    filterset_fields = ["status", "kind"]
    # Pages when asked for (?page= / ?page_size=); the whole list otherwise,
    # which is what the frontend already deployed expects (B-1).
    pagination_class = PagedOnRequest

    def get_queryset(self):
        queryset = super().get_queryset()
        if is_leader(self.request.user):
            return queryset
        return queryset.filter(requested_by=self.request.user)

    def _note(self):
        return str(self.request.data.get("note", "")).strip()

    def _reviewable(self):
        change_request = self.get_object()
        user = self.request.user
        if not (is_admin(user) or (is_leader(user) and change_request.kind != "school")):
            raise PermissionDenied("Only admins can approve changes to the school's settings."
                                   if is_leader(user) else "Only school admins and leadership can do this.")
        return change_request

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        change_request = services.approve(self._reviewable(), request.user, self._note())
        return Response(self.get_serializer(change_request).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        change_request = services.reject(self._reviewable(), request.user, self._note())
        return Response(self.get_serializer(change_request).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        change_request = self.get_object()
        if change_request.requested_by_id != request.user.id:
            raise PermissionDenied("Only the person who asked can cancel a request.")
        if change_request.status != ChangeRequest.Status.PENDING:
            raise ValidationError("Only requests that are waiting for approval can be cancelled.")
        change_request.status = ChangeRequest.Status.CANCELLED
        change_request.reviewed_at = timezone.now()
        change_request.save(update_fields=["status", "reviewed_at"])
        log_activity(
            school=change_request.school, actor=request.user, action="change_request.cancelled",
            target=change_request, summary=f"Cancelled their request to: {change_request.summary}",
        )
        return Response(self.get_serializer(change_request).data)
