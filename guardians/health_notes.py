"""
Parents suggesting a change to their child's health notes.

The school keeps the record, so a parent's suggestion is a pending
approvals.ChangeRequest (kind "student", an update of `medical_notes` only)
that a school admin approves or rejects in Approvals, exactly like a
teacher's request; approving replays it through StudentViewSet. The note
text lives only in the request's `data` (seen by the school's admins and
the parent who sent it), never in its summary or the activity log.
"""
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from activity.services import display_name, log_activity, student_name
from approvals.models import ChangeRequest

MAX_LENGTH = 2000


def _requests(user, student):
    return ChangeRequest.objects.filter(
        school=student.school, requested_by=user, kind="student", target_id=student.pk,
        operation=ChangeRequest.Operation.UPDATE, data__has_key="medical_notes",
    ).order_by("-created_at", "-id")


def latest(user, student):
    return _requests(user, student).first()


def as_data(change_request):
    if change_request is None:
        return None
    return {
        "id": change_request.id,
        "medical_notes": change_request.data.get("medical_notes", ""),
        "reason": change_request.reason,
        "status": change_request.status,
        "status_label": change_request.get_status_display(),
        "review_note": change_request.review_note,
        "created_at": change_request.created_at,
        "reviewed_at": change_request.reviewed_at,
    }


def suggest(user, student, data):
    if not student.is_active:
        raise ValidationError("This child is no longer at the school, so their details can't be changed here.")
    if _requests(user, student).filter(status=ChangeRequest.Status.PENDING).exists():
        raise ValidationError(
            "You've already suggested a change that the school hasn't looked at yet. "
            "Withdraw it first if you want to send a different one."
        )
    notes = data.get("medical_notes")
    if not isinstance(notes, str):
        raise ValidationError({"medical_notes": ["Write the health notes, or leave the box empty to clear them."]})
    notes = notes.strip()
    if len(notes) > MAX_LENGTH:
        raise ValidationError({"medical_notes": [f"Please keep it under {MAX_LENGTH} characters."]})
    if notes == (student.medical_notes or "").strip():
        raise ValidationError("That's what the school already has, so there's nothing to change.")
    change_request = ChangeRequest.objects.create(
        school=student.school,
        requested_by=user,
        requested_by_name=display_name(user),
        kind="student",
        operation=ChangeRequest.Operation.UPDATE,
        target_id=student.pk,
        data={"medical_notes": notes},
        summary=f"Change health notes for {student_name(student)} (suggested by a parent)",
        reason=str(data.get("reason", "")).strip()[:500],
    )
    log_activity(
        school=student.school, actor=user, action="change_request.created", target=change_request,
        summary=f"Asked for approval to: {change_request.summary}",
    )
    return change_request


def withdraw(user, student):
    change_request = _requests(user, student).filter(status=ChangeRequest.Status.PENDING).first()
    if change_request is None:
        raise NotFound("There's no suggestion waiting to be withdrawn.")
    change_request.status = ChangeRequest.Status.CANCELLED
    change_request.reviewed_at = timezone.now()
    change_request.save(update_fields=["status", "reviewed_at"])
    log_activity(
        school=student.school, actor=user, action="change_request.cancelled", target=change_request,
        summary=f"Withdrew their request to: {change_request.summary}",
    )
    return change_request
