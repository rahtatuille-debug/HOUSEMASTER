from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from accounts.permissions import HasSchoolProfile
from accounts.scoping import RECORDS, visible_students
from accounts.tokens import tokens_for
from activity.services import display_name, log_activity, student_name
from gradebook.levels import school_summary

from . import services
from .models import StudentAccount

# Each login's password is hashed (about a second each), so a request makes at most this many;
# the app sends bigger groups in batches.
MAX_AT_ONCE = 40


def _row(student, account=None):
    account = account if account is not None else getattr(student, "account", None)
    return {
        "student": student.id, "name": student_name(student),
        "class_name": student.school_class.name if student.school_class_id else None,
        "school_class": student.school_class_id, "has_account": account is not None,
        "username": account.user.username if account else None,
        "active": bool(account and account.user.is_active),
        "must_change_password": bool(account and account.must_change_password),
        "last_login": account.user.last_login if account else None,
    }


class StudentAccountViewSet(ViewSet):
    """
    Student logins, for admins, leadership and the secretary. GET
    ?school_class=: active students with their account (if any). POST
    {students: [ids]}: make accounts for those without one; the answer
    holds each starting password, shown this once. Per student (by student
    id): reset/ (a new starting password), disable/, enable/, DELETE.
    """

    permission_classes = [IsAuthenticated, HasSchoolProfile]

    def _check(self):
        if not services.can_manage(self.request.user):
            raise PermissionDenied("Only an admin, leadership or the secretary can manage student accounts.")

    def _students(self):
        return (visible_students(self.request.user, RECORDS).filter(is_active=True)
                .select_related("school_class", "account__user").order_by("school_class__name", "last_name", "first_name"))

    def _student(self, pk):
        try:
            return self._students().get(pk=pk)
        except (ValueError, TypeError, Exception):
            raise NotFound("Student not found.")

    def list(self, request):
        self._check()
        students = self._students()
        if request.query_params.get("school_class"):
            students = students.filter(school_class_id=request.query_params["school_class"])
        return Response([_row(s) for s in students])

    def create(self, request):
        self._check()
        ids = request.data.get("students")
        if not isinstance(ids, list) or not ids:
            raise ValidationError({"students": ["Choose at least one student."]})
        if len(ids) > MAX_AT_ONCE:
            raise ValidationError({"students": [f"Choose at most {MAX_AT_ONCE} students at a time."]})
        try:
            ids = {int(i) for i in ids}
        except (TypeError, ValueError):
            raise ValidationError({"students": ["Student not found."]})
        students = list(self._students().filter(pk__in=ids))
        if len(students) != len(ids):
            raise ValidationError({"students": ["Student not found."]})
        made = []
        name = display_name(request.user)
        with transaction.atomic():
            for s in students:
                if getattr(s, "account", None) is None:
                    account, password = services.create(s, name)
                    made.append({**_row(s, account), "password": password})
        if made:
            who = made[0]["name"] if len(made) == 1 else f"{len(made)} students"
            log_activity(school=request.user.profile.school, actor=request.user, action="student_accounts.created",
                         summary=f"Made student accounts for {who}", students=[m["student"] for m in made])
        return Response({"created": made, "already": len(students) - len(made)}, status=201)

    def destroy(self, request, pk=None):
        self._check()
        student = self._student(pk)
        account = getattr(student, "account", None)
        if account is None:
            raise ValidationError({"student": ["This student has no account."]})
        account.delete()
        log_activity(school=student.school, actor=request.user, action="student_accounts.deleted", target=student,
                     summary=f"Removed {student_name(student)}'s student account")
        return Response(status=204)

    def _account(self, pk):
        self._check()
        student = self._student(pk)
        account = getattr(student, "account", None)
        if account is None:
            raise ValidationError({"student": ["This student has no account."]})
        return student, account

    @action(detail=True, methods=["post"])
    def reset(self, request, pk=None):
        student, account = self._account(pk)
        password = services.reset(account)
        log_activity(school=student.school, actor=request.user, action="student_accounts.reset", target=student,
                     summary=f"Gave {student_name(student)} a new starting password")
        return Response({**_row(student, account), "password": password})

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        return self._set_active(pk, False)

    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        return self._set_active(pk, True)

    def _set_active(self, pk, active):
        student, account = self._account(pk)
        account.user.is_active = active
        account.user.save(update_fields=["is_active"])
        log_activity(school=student.school, actor=self.request.user, target=student,
                     action="student_accounts.enabled" if active else "student_accounts.disabled",
                     summary=f"{'Turned on' if active else 'Turned off'} {student_name(student)}'s student account")
        return Response(_row(student, account))


def _signed_in_student(request):
    account = services.account_of(request.user)
    if account is None or not account.student.is_active:
        raise PermissionDenied("This is not a student account.")
    return account


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_me(request):
    """Who the signed-in student is, and whether they must choose a new password first."""
    account = _signed_in_student(request)
    student = account.student
    return Response({
        "id": request.user.id, "role": "student", "name": student_name(student), "first_name": student.first_name,
        "student_id": student.id, "username": request.user.username,
        "class_name": student.school_class.name if student.school_class_id else None,
        "must_change_password": account.must_change_password, "school": school_summary(student.school),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def student_password(request):
    """POST {current_password, new_password}: the student chooses their own password. Answers with new sign-in tokens."""
    account = _signed_in_student(request)
    user = request.user
    if not user.check_password(str(request.data.get("current_password", ""))):
        raise ValidationError({"current_password": ["That isn't your current password."]})
    new = str(request.data.get("new_password", ""))
    if new == str(request.data.get("current_password", "")):
        raise ValidationError({"new_password": ["Choose a password that is different from the one you were given."]})
    try:
        validate_password(new, user)
    except DjangoValidationError as err:
        raise ValidationError({"new_password": list(err.messages)})
    user.set_password(new)
    user.save()
    account.must_change_password = False
    account.save(update_fields=["must_change_password"])
    log_activity(school=account.student.school, actor=user, action="student_accounts.password_changed",
                 target=account.student, summary=f"{student_name(account.student)} chose a new password")
    return Response(tokens_for(user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def student_hand_in(request, assignment_id):
    """
    POST {done: true, answer?}: hand in homework (marked done, with a typed
    answer or a link). {done: false}: take it back. Not once the teacher
    has recorded it.
    """
    from homework.models import HomeworkRecord
    from homework.services import assignments_for_student

    account = _signed_in_student(request)
    student = account.student
    assignment = assignments_for_student(student).filter(pk=assignment_id).first()
    if assignment is None:
        raise NotFound("Homework not found.")
    record = HomeworkRecord.objects.filter(assignment=assignment, student=student).first()
    if record is not None and record.status:
        raise ValidationError({"detail": ["Your teacher has already recorded this homework."]})
    done = request.data.get("done") is True
    answer = str(request.data.get("answer") or "").strip()
    if len(answer) > 4000:
        raise ValidationError({"answer": ["Keep it under 4,000 characters, or paste a link to your work."]})
    record, _ = HomeworkRecord.objects.get_or_create(assignment=assignment, student=student)
    record.done_at = timezone.now() if done else None
    record.answer = answer if done else ""
    record.save(update_fields=["done_at", "answer", "updated_at"])
    return Response({"id": assignment.id, "done_at": record.done_at, "answer": record.answer})
