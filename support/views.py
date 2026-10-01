from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import visible_students
from activity.services import display_name, log_activity, student_name
from reporting.analytics import SchoolGrades

from . import services
from .models import SupportConcern
from .serializers import SupportConcernSerializer


def _visible_ids(user):
    return list(visible_students(user).filter(is_active=True).values_list("id", flat=True))


class SupportConcernViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                            mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    Students marked as needing support, for staff who can see them.
    POST {student, term?, reasons: [codes], note, support_plan, review_date}
    confirms a suggestion (or marks a student by hand, with no reasons) and
    tells the parents. PATCH changes the note, plan or review date.
    /resolve/ closes it; /dismiss/ {student, term} records that a suggestion
    was looked at and isn't needed. Filter with ?status= and ?student=.
    """

    serializer_class = SupportConcernSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = SupportConcern.objects.filter(
            school=user.profile.school, student__in=visible_students(user),
        ).select_related("student__school_class__year_group", "term")
        for field in ("status", "student"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    def _student_and_term(self, data):
        user = self.request.user
        try:
            student = visible_students(user).get(pk=data.get("student"), is_active=True)
        except Exception:
            raise ValidationError({"student": ["Student not found."]})
        term = None
        if data.get("term"):
            term = student.school.terms.filter(pk=data.get("term")).first()
            if term is None:
                raise ValidationError({"term": ["Term not found."]})
        return student, term

    def _open_exists(self, student):
        if student.support_concerns.filter(status=SupportConcern.Status.OPEN).exists():
            raise ValidationError(f"{student_name(student)} is already marked as needing support.")

    def create(self, request, *args, **kwargs):
        student, term = self._student_and_term(request.data)
        codes = request.data.get("reasons") or []
        if not isinstance(codes, list) or any(c not in services.REASONS for c in codes):
            raise ValidationError({"reasons": [f"Choose from: {', '.join(services.REASONS)}."]})
        self._open_exists(student)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # The reasons as they stand now, worded with the student's numbers.
        data = SchoolGrades(student.school)
        found = {r["code"]: r for r in services.warning_signs(data, term or data.term(None), [student.id])
                 .get(student.id, [])}
        reasons = [found.get(code, {"code": code, "label": services.REASONS[code]}) for code in dict.fromkeys(codes)]
        user = request.user
        try:
            with transaction.atomic():
                concern = serializer.save(
                    school=student.school, student=student, term=term or data.term(None),
                    status=SupportConcern.Status.OPEN, reasons=reasons,
                    source=SupportConcern.Source.AUTO if reasons else SupportConcern.Source.MANUAL,
                    created_by=user, created_by_name=display_name(user),
                )
        except IntegrityError:
            raise ValidationError(f"{student_name(student)} is already marked as needing support.")
        log_activity(school=student.school, actor=user, action="support.opened", target=student,
                     summary=f"Marked {student_name(student)} as needing support")
        services.notify_parents(concern, user)
        return Response(self.get_serializer(concern).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        concern = self.get_object()
        if concern.status != SupportConcern.Status.OPEN:
            raise ValidationError("Only an open concern can be changed.")
        allowed = {k: v for k, v in request.data.items() if k in ("note", "support_plan", "review_date")}
        serializer = self.get_serializer(concern, data=allowed, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_activity(school=concern.school, actor=request.user, action="support.updated", target=concern.student,
                     summary=f"Updated the support plan for {student_name(concern.student)}")
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        concern = self.get_object()
        if concern.status != SupportConcern.Status.OPEN:
            raise ValidationError("This concern is already closed.")
        concern.status = SupportConcern.Status.RESOLVED
        concern.closed_by = request.user
        concern.closed_by_name = display_name(request.user)
        concern.closed_at = timezone.now()
        concern.closing_note = str(request.data.get("note", "")).strip()[:2000]
        concern.save()
        log_activity(school=concern.school, actor=request.user, action="support.resolved", target=concern.student,
                     summary=f"Marked {student_name(concern.student)} as no longer needing support")
        return Response(self.get_serializer(concern).data)

    @action(detail=False, methods=["post"])
    def dismiss(self, request):
        student, term = self._student_and_term(request.data)
        self._open_exists(student)
        user = request.user
        concern = SupportConcern.objects.create(
            school=student.school, student=student, term=term or SchoolGrades(student.school).term(None),
            status=SupportConcern.Status.DISMISSED, source=SupportConcern.Source.AUTO,
            created_by=user, created_by_name=display_name(user), closed_by=user,
            closed_by_name=display_name(user), closed_at=timezone.now(),
        )
        log_activity(school=student.school, actor=user, action="support.dismissed", target=student,
                     summary=f"Dismissed the support suggestion for {student_name(student)}")
        return Response(self.get_serializer(concern).data, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def suggestions(request):
    """?term=<id, optional: the latest graded term>. Students the viewer can see who show warning signs."""
    user = request.user
    data = SchoolGrades(user.profile.school)
    term = data.term(request.query_params.get("term"))
    ids = [sid for sid in _visible_ids(user) if sid in data.students]
    found = services.suggestions(data, term, ids)
    results = []
    for sid, reasons in found.items():
        s = data.students[sid]
        klass = s.school_class
        results.append({"student": sid, "name": f"{s.first_name} {s.last_name}",
                         "class_name": f"{klass.year_group.name} — {klass.name}" if klass else None,
                         "reasons": reasons})
    results.sort(key=lambda r: (-len(r["reasons"]), r["name"]))
    return Response({"term": term.id if term else None, "term_name": term.name if term else None,
                     "results": results})
