from rest_framework import viewsets
from rest_framework.decorators import action, api_view, parser_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.permissions import HasSchoolProfile
from approvals.mixins import ApprovalRequiredMixin
from accounts.scoping import ACADEMIC, check_can_grade, limit_to_visible_students
from activity.services import log_activity, student_name
from housemaster.pagination import LongListPagination

from .choices import check_takes
from .locks import check_term_open

from .models import AssessmentType, Subject, Term, Grade
from .serializers import AssessmentTypeSerializer, SubjectSerializer, TermSerializer, GradeSerializer


class SubjectViewSet(ApprovalRequiredMixin, SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Subject.objects.select_related("school")
    serializer_class = SubjectSerializer
    school_lookup = "school"
    approval_kind = "subject"
    approval_label = "subject"

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class TermViewSet(ApprovalRequiredMixin, SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Term.objects.all()
    serializer_class = TermSerializer
    school_lookup = "school"
    approval_kind = "term"
    approval_label = "term"

    def check_change_request(self, serializer):
        if serializer.instance is not None:
            check_term_open(serializer.instance)

    def perform_destroy(self, instance):
        check_term_open(instance)
        instance.delete()

    def _set_locked(self, request, locked):
        from django.utils import timezone

        if not (hasattr(request.user, "profile") and request.user.profile.is_admin):
            raise PermissionDenied("Only admins can lock or unlock terms.")
        term = self.get_object()
        if term.is_locked != locked:
            term.is_locked = locked
            term.locked_at = timezone.now() if locked else None
            term.save(update_fields=["is_locked", "locked_at"])
            log_activity(
                school=term.school, actor=request.user, action="term.locked" if locked else "term.unlocked",
                target=term, summary=f"{'Locked' if locked else 'Unlocked'} {term.name}",
            )
        return Response(self.get_serializer(term).data)

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        return self._set_locked(request, True)

    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        return self._set_locked(request, False)

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class AssessmentTypeViewSet(ApprovalRequiredMixin, SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """How marks are weighted, e.g. CAT 30 and End-term exam 70. Teachers' changes need approval."""
    queryset = AssessmentType.objects.all()
    serializer_class = AssessmentTypeSerializer
    school_lookup = "school"
    approval_kind = "assessment_type"
    approval_label = "assessment type"

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class GradeViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    # Ordered by id so pages are stable (F-14).
    queryset = Grade.objects.order_by("id")
    serializer_class = GradeSerializer
    pagination_class = LongListPagination
    filterset_fields = ["student", "subject", "term"]
    school_lookup = "student__school"

    def get_queryset(self):
        # Teachers see every subject's grades for students in their classes,
        # but can only add or change grades for the subjects they teach.
        return limit_to_visible_students(super().get_queryset(), self.request.user, area=ACADEMIC)

    def _validate_related(self, validated_data):
        self.check_belongs_to_school(validated_data["student"].school, "student")
        self.check_belongs_to_school(validated_data["subject"].school, "subject")
        self.check_belongs_to_school(validated_data["term"].school, "term")

    @staticmethod
    def _describe(grade):
        return f"{grade.subject.name} grade for {student_name(grade.student)} ({grade.term.name})"

    def perform_create(self, serializer):
        self._validate_related(serializer.validated_data)
        check_term_open(serializer.validated_data["term"])
        check_can_grade(self.request.user, serializer.validated_data["student"],
                        serializer.validated_data["subject"])
        check_takes(serializer.validated_data["student"], serializer.validated_data["subject"])
        grade = serializer.save()
        log_activity(
            school=self.get_school(), actor=self.request.user, action="grade.created", target=grade,
            summary=f"Added {self._describe(grade)}: {grade.score}/{grade.max_score}",
            score=str(grade.score), max_score=str(grade.max_score),
        )

    def perform_update(self, serializer):
        student = serializer.validated_data.get("student", serializer.instance.student)
        subject = serializer.validated_data.get("subject", serializer.instance.subject)
        term = serializer.validated_data.get("term", serializer.instance.term)
        self.check_belongs_to_school(student.school, "student")
        self.check_belongs_to_school(subject.school, "subject")
        self.check_belongs_to_school(term.school, "term")
        check_can_grade(self.request.user, serializer.instance.student, serializer.instance.subject)
        check_can_grade(self.request.user, student, subject)
        if (student, subject) != (serializer.instance.student, serializer.instance.subject):
            check_takes(student, subject)
        check_term_open(serializer.instance.term)
        check_term_open(term)
        old = f"{serializer.instance.score}/{serializer.instance.max_score}"
        grade = serializer.save()
        new = f"{grade.score}/{grade.max_score}"
        log_activity(
            school=self.get_school(), actor=self.request.user, action="grade.updated", target=grade,
            summary=f"Changed {self._describe(grade)} from {old} to {new}",
            old=old, new=new,
        )

    def perform_destroy(self, instance):
        check_can_grade(self.request.user, instance.student, instance.subject)
        check_term_open(instance.term)
        log_activity(
            school=self.get_school(), actor=self.request.user, action="grade.deleted", target=instance,
            summary=f"Deleted {self._describe(instance)} ({instance.score}/{instance.max_score})",
            score=str(instance.score), max_score=str(instance.max_score),
        )
        instance.delete()


def _marksheet_params(request, data):
    """The class, subject, term, assessment type and "out of" a mark sheet is for, checked like typed marks."""
    from decimal import Decimal, InvalidOperation

    from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

    from accounts.scoping import can_grade_class
    from students.models import SchoolClass

    from .models import AssessmentType, Subject, Term

    school = request.user.profile.school

    def find(model, key, **scope):
        value = data.get(key)
        if not str(value or "").isdigit():
            raise ValidationError({key: "Choose one."})
        found = model.objects.filter(pk=value, **scope).first()
        if found is None:
            raise NotFound(f"{key.replace('_', ' ').capitalize()} not found.")
        return found

    school_class = find(SchoolClass, "school_class", year_group__school=school)
    subject = find(Subject, "subject", school=school)
    term = find(Term, "term", school=school)
    kind = find(AssessmentType, "assessment_type", school=school) if data.get("assessment_type") else None
    try:
        max_score = Decimal(str(data.get("max_score") or "100"))
    except InvalidOperation:
        raise ValidationError({"max_score": "Out of must be a number."})
    if not max_score.is_finite() or max_score <= 0 or max_score > Decimal("999.99"):
        raise ValidationError({"max_score": "Out of must be more than 0 and at most 999.99."})
    if not can_grade_class(request.user, school_class.id, subject):
        raise PermissionDenied(f"You don't teach {subject.name} to {school_class.name}.")
    return school_class, subject, term, kind, max_score


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def marksheet_template(request):
    """?school_class=&subject=&term=&assessment_type=&max_score=: the class's mark sheet to fill in (Excel)."""
    from django.http import HttpResponse

    from .marksheet import template

    school_class, subject, term, kind, max_score = _marksheet_params(request, request.query_params)
    response = HttpResponse(template(school_class, subject, term, kind, max_score),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    name = "".join(c if c.isalnum() else "-" for c in f"marks-{school_class.name}-{subject.name}-{term.name}").lower()
    response["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
@parser_classes([MultiPartParser])
def marksheet_import(request):
    """
    A filled-in mark sheet as `file`, with school_class, subject, term, assessment_type (optional) and max_score.
    Without commit=true it's a preview: every row is checked and nothing is saved. With commit=true the rows that
    passed are saved as marks.
    """
    from rest_framework.exceptions import ValidationError

    from .marksheet import MarkSheetError, import_marks

    school_class, subject, term, kind, max_score = _marksheet_params(request, request.data)
    upload = request.FILES.get("file")
    if upload is None:
        raise ValidationError({"file": "Choose the filled-in mark sheet."})
    commit = str(request.data.get("commit", "")).lower() == "true"
    check_term_open(term)  # nothing can change in a locked term, so say so before checking the file
    try:
        result = import_marks(upload, request.user, school_class, subject, term, kind, max_score, commit)
    except MarkSheetError as exc:
        raise ValidationError({"file": str(exc)})
    return Response(result)
