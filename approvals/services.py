from importlib import import_module
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from activity.services import display_name, log_activity

from .mixins import PAST_TENSE
from .models import ChangeRequest

# Which viewset handles each kind of change request. Imported lazily to
# avoid a circular import (those viewsets import ApprovalRequiredMixin).
VIEWSETS = {
    "school": "students.views.SchoolViewSet",
    "year_group": "students.views.YearGroupViewSet",
    "school_class": "students.views.SchoolClassViewSet",
    "student": "students.views.StudentViewSet",
    "subject": "gradebook.views.SubjectViewSet",
    "assessment_type": "gradebook.views.AssessmentTypeViewSet",
    "term": "gradebook.views.TermViewSet",
}


def _viewset_for(kind, admin_user, action):
    module_path, class_name = VIEWSETS[kind].rsplit(".", 1)
    view = getattr(import_module(module_path), class_name)()
    view.request = SimpleNamespace(user=admin_user, query_params={}, data={})
    view.action = action
    view.format_kwarg = None
    view.kwargs = {}
    view.args = ()
    return view


@transaction.atomic
def approve(change_request, admin_user, note=""):
    """
    Carry out a pending change request as the approving admin, through the
    same viewset code a direct admin change uses. Raises ValidationError
    (leaving the request pending) if the change no longer makes sense, for
    example because the item was deleted in the meantime.
    """
    if change_request.status != ChangeRequest.Status.PENDING:
        raise ValidationError("Only requests that are waiting for approval can be approved.")

    op = change_request.operation
    view = _viewset_for(change_request.kind, admin_user, {"create": "create", "update": "partial_update",
                                                          "delete": "destroy"}[op])
    context = {"request": view.request, "view": view, "format": None}
    serializer_class = view.get_serializer_class()

    target = None
    if op in ("update", "delete"):
        try:
            target = view.get_queryset().get(pk=change_request.target_id)
        except view.get_queryset().model.DoesNotExist:
            raise ValidationError("The item this request is about no longer exists.")

    if op == "create":
        serializer = serializer_class(data=change_request.data, context=context)
        serializer.is_valid(raise_exception=True)
        view.check_change_request(serializer)
        view.perform_create(serializer)
        target = serializer.instance
    elif op == "update":
        serializer = serializer_class(target, data=change_request.data, partial=True, context=context)
        serializer.is_valid(raise_exception=True)
        view.check_change_request(serializer)
        view.perform_update(serializer)
    else:
        view.perform_destroy(target)
        target = None

    change_request.status = ChangeRequest.Status.APPROVED
    change_request.reviewed_by = admin_user
    change_request.reviewed_by_name = display_name(admin_user)
    change_request.reviewed_at = timezone.now()
    change_request.review_note = note[:500]
    change_request.save()

    log_activity(
        school=change_request.school, actor=admin_user,
        action=f"{change_request.kind}.{PAST_TENSE[op]}", target=target,
        summary=f"{change_request.summary} (approved request from {change_request.requested_by_name})",
        change_request=change_request.id,
    )
    return change_request


def reject(change_request, admin_user, note=""):
    if change_request.status != ChangeRequest.Status.PENDING:
        raise ValidationError("Only requests that are waiting for approval can be rejected.")
    change_request.status = ChangeRequest.Status.REJECTED
    change_request.reviewed_by = admin_user
    change_request.reviewed_by_name = display_name(admin_user)
    change_request.reviewed_at = timezone.now()
    change_request.review_note = note[:500]
    change_request.save()
    log_activity(
        school=change_request.school, actor=admin_user, action="change_request.rejected",
        target=change_request,
        summary=f"Rejected {change_request.requested_by_name}'s request to: {change_request.summary}",
        note=change_request.review_note,
    )
    return change_request
