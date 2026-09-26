from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.scoping import is_admin
from activity.services import display_name, log_activity

from .models import ChangeRequest

PAST_TENSE = {"create": "created", "update": "updated", "delete": "deleted"}


def _show(value):
    if value is None or value == "":
        return "none"
    return str(getattr(value, "name", value))


class ApprovalRequiredMixin:
    """
    For viewsets where teachers' changes need an admin's approval.

    Admins' changes go through straight away (and are logged). When a
    teacher makes one of the `approval_operations`, the request is checked
    exactly as it would be for an admin, then saved as a pending
    ChangeRequest instead, and the response is 202 Accepted with that
    request. Once an admin approves it, approvals.services replays it
    through this same viewset's perform_create/perform_update/
    perform_destroy.

    Set `approval_kind` (a key in approvals.services.VIEWSETS) and
    `approval_label` (e.g. "subject"), and override `describe()` if the
    object has no `name`.
    """

    approval_kind = None
    approval_label = None
    approval_operations = {"create", "update", "delete"}

    def describe(self, obj):
        return obj.name

    def check_change_request(self, serializer):
        """Extra checks that must pass before a change is saved or requested."""

    def _needs_approval(self, operation):
        return operation in self.approval_operations and not is_admin(self.request.user)

    def _summary(self, operation, instance, serializer):
        label = self.approval_label
        if operation == "create":
            data = serializer.validated_data
            name = data.get("name") or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
            return f'Add {label} "{name}"'
        if operation == "delete":
            return f'Delete {label} "{self.describe(instance)}"'
        changes = []
        for field, new in serializer.validated_data.items():
            old = getattr(instance, field)
            if old != new:
                verbose = instance._meta.get_field(field).verbose_name
                changes.append(f"{verbose} from {_show(old)} to {_show(new)}")
        if not changes:
            return None
        return f'Change {label} "{self.describe(instance)}": ' + ", ".join(changes)

    def _request_approval(self, operation, instance, serializer, summary):
        data = {}
        if serializer is not None:
            # Store what was sent, limited to fields the serializer accepts.
            data = {k: v for k, v in serializer.initial_data.items() if k in serializer.validated_data}
        change_request = ChangeRequest.objects.create(
            school=self.get_school(),
            requested_by=self.request.user,
            requested_by_name=display_name(self.request.user),
            kind=self.approval_kind,
            operation=operation,
            target_id=instance.pk if instance is not None else None,
            data=data,
            summary=summary,
            reason=str(self.request.data.get("reason", ""))[:500],
        )
        log_activity(
            school=change_request.school, actor=self.request.user, action="change_request.created",
            target=change_request, summary=f"Asked for approval to: {summary}",
        )
        from .serializers import ChangeRequestSerializer

        return Response(
            {
                "detail": "Sent to an admin for approval.",
                "change_request": ChangeRequestSerializer(change_request).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    def _log_direct(self, operation, target, summary):
        log_activity(
            school=self.get_school(), actor=self.request.user,
            action=f"{self.approval_kind}.{PAST_TENSE[operation]}", target=target, summary=summary,
        )

    def create(self, request, *args, **kwargs):
        if "create" not in self.approval_operations:
            return super().create(request, *args, **kwargs)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.check_change_request(serializer)
        summary = self._summary("create", None, serializer)
        if self._needs_approval("create"):
            return self._request_approval("create", None, serializer, summary)
        self.perform_create(serializer)
        self._log_direct("create", serializer.instance, summary)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        if "update" not in self.approval_operations:
            return super().update(request, *args, **kwargs)
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.check_change_request(serializer)
        summary = self._summary("update", instance, serializer)
        if self._needs_approval("update"):
            if summary is None:
                raise ValidationError("Nothing would change.")
            return self._request_approval("update", instance, serializer, summary)
        self.perform_update(serializer)
        if summary is not None:
            self._log_direct("update", serializer.instance, summary)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if "delete" not in self.approval_operations:
            return super().destroy(request, *args, **kwargs)
        instance = self.get_object()
        summary = self._summary("delete", instance, None)
        if self._needs_approval("delete"):
            return self._request_approval("delete", instance, None, summary)
        self._log_direct("delete", instance, summary)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)
