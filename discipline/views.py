from datetime import date

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import is_admin, visible_students
from activity.services import display_name, log_activity, student_name
from students.localtime import school_localdate

from . import services
from .models import DisciplineIncident
from .serializers import DisciplineIncidentSerializer

EDITABLE = ("date", "category", "severity", "description", "action", "action_detail", "staff_notes",
            "shared_with_parents")


class DisciplineIncidentViewSet(viewsets.ModelViewSet):
    """
    Behaviour incidents, for staff who can see the student (admins: everyone;
    teachers: their own classes). POST {student, date?, category, severity,
    description, action, action_detail, staff_notes, shared_with_parents}.
    Sharing with parents emails them. The person who recorded it or an admin
    may change it; only an admin may delete it. Filter with ?student=,
    ?category=, ?severity=, ?from= and ?to= (dates).
    The activity log names the student and the category, never the
    description or staff notes.
    """

    serializer_class = DisciplineIncidentSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = DisciplineIncident.objects.filter(
            school=user.profile.school, student__in=visible_students(user),
        ).select_related("student__school_class")
        params = self.request.query_params
        for field in ("student", "category", "severity"):
            if params.get(field):
                queryset = queryset.filter(**{field: params[field]})
        for param, lookup in (("from", "date__gte"), ("to", "date__lte")):
            if params.get(param):
                try:
                    queryset = queryset.filter(**{lookup: date.fromisoformat(params[param])})
                except ValueError:
                    raise ValidationError({param: ["Use a date like 2026-10-08."]})
        return queryset

    def _check_date(self, serializer, school):
        when = serializer.validated_data.get("date")
        if when and when > school_localdate(school):
            raise ValidationError({"date": ["The date can't be in the future."]})

    def create(self, request, *args, **kwargs):
        user = request.user
        try:
            student = visible_students(user).get(pk=request.data.get("student"), is_active=True)
        except Exception:
            raise ValidationError({"student": ["Student not found."]})
        data = {k: v for k, v in request.data.items() if k in EDITABLE}
        data.setdefault("date", school_localdate(student.school).isoformat())
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self._check_date(serializer, student.school)
        incident = serializer.save(school=student.school, student=student, recorded_by=user,
                                   recorded_by_name=display_name(user))
        log_activity(school=student.school, actor=user, action="discipline.recorded", target=student,
                     summary=f"Recorded a discipline incident for {student_name(student)} "
                             f"({incident.get_category_display()})")
        emailed = services.notify_parents(incident) if incident.shared_with_parents else 0
        return Response({**self.get_serializer(incident).data, "parents_emailed": emailed}, status=201)

    def partial_update(self, request, *args, **kwargs):
        incident = self.get_object()
        user = request.user
        if not (is_admin(user) or incident.recorded_by_id == user.id):
            raise PermissionDenied("Only the person who recorded this, or an admin, can change it.")
        was_shared = incident.shared_with_parents
        data = {k: v for k, v in request.data.items() if k in EDITABLE}
        serializer = self.get_serializer(incident, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self._check_date(serializer, incident.school)
        incident = serializer.save()
        log_activity(school=incident.school, actor=user, action="discipline.updated", target=incident.student,
                     summary=f"Updated a discipline record for {student_name(incident.student)}")
        emailed = services.notify_parents(incident) if incident.shared_with_parents and not was_shared else 0
        return Response({**self.get_serializer(incident).data, "parents_emailed": emailed})

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        incident = self.get_object()
        if not is_admin(request.user):
            raise PermissionDenied("Only an admin can delete a discipline record.")
        student = incident.student
        summary = (f"Deleted a discipline record for {student_name(student)} "
                   f"({incident.get_category_display()}, {incident.date.isoformat()})")
        incident.delete()
        log_activity(school=student.school, actor=request.user, action="discipline.deleted", target=student,
                     summary=summary)
        return Response(status=204)

    @action(detail=False, methods=["get"])
    def choices(self, request):
        """The categories, severities and actions to offer, as [value, label] pairs."""
        return Response({
            "categories": DisciplineIncident.Category.choices,
            "severities": DisciplineIncident.Severity.choices,
            "actions": DisciplineIncident.Action.choices,
        })
