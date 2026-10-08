from datetime import date

from django.db import transaction
from django.db.models import Count, Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import is_admin, is_leader, visible_students
from activity.services import display_name, log_activity, student_name
from students.localtime import school_localdate

from . import services
from .models import DisciplineIncident, Merit
from .serializers import DisciplineIncidentSerializer, MeritSerializer

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
        if not (is_leader(user) or incident.recorded_by_id == user.id):
            raise PermissionDenied("Only the person who recorded this, leadership or an admin can change it.")
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


MERIT_EDITABLE = ("date", "category", "points", "reason", "shared_with_parents")
MAX_AT_ONCE = 200


class MeritViewSet(viewsets.ModelViewSet):
    """
    Merits: rewards for students, for staff who can see the student.
    POST {student or students: [ids], date?, category, points (1-5), reason,
    shared_with_parents (default true)} gives the same merit to each
    student, e.g. a whole class. Parents see shared merits in the app (no
    email). The giver, leadership or an admin may change or remove one.
    Filter with ?student=, ?category=, ?school_class=, ?from= and ?to=.
    The activity log names the students and the category, never the reason.
    """

    serializer_class = MeritSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = Merit.objects.filter(
            school=user.profile.school, student__in=visible_students(user),
        ).select_related("student__school_class")
        params = self.request.query_params
        for param, field in (("student", "student"), ("category", "category"), ("school_class", "student__school_class")):
            if params.get(param):
                queryset = queryset.filter(**{field: params[param]})
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
        many = "students" in request.data
        ids = request.data.get("students") if many else [request.data.get("student")]
        if not isinstance(ids, list) or not ids:
            raise ValidationError({"students": ["Choose at least one student."]})
        if len(ids) > MAX_AT_ONCE:
            raise ValidationError({"students": [f"Choose at most {MAX_AT_ONCE} students at a time."]})
        try:
            ids = {int(i) for i in ids}
        except (TypeError, ValueError):
            raise ValidationError({"students": ["Student not found."]})
        students = list(visible_students(user).filter(pk__in=ids, is_active=True).select_related("school_class"))
        if len(students) != len(ids):
            raise ValidationError({"students" if many else "student": ["Student not found."]})
        school = user.profile.school
        data = {k: v for k, v in request.data.items() if k in MERIT_EDITABLE}
        data.setdefault("date", school_localdate(school).isoformat())
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self._check_date(serializer, school)
        name = display_name(user)
        with transaction.atomic():
            merits = [Merit.objects.create(school=school, student=s, awarded_by=user, awarded_by_name=name,
                                           **serializer.validated_data)
                      for s in sorted(students, key=lambda s: (s.last_name, s.first_name, s.id))]
            label = merits[0].get_category_display()
            who = student_name(students[0]) if len(students) == 1 else f"{len(students)} students"
            log_activity(school=school, actor=user, action="discipline.merit_awarded",
                         target=students[0] if len(students) == 1 else None,
                         summary=f"Gave a merit to {who} ({label}, {merits[0].points} point"
                                 f"{'' if merits[0].points == 1 else 's'})",
                         students=[s.id for s in students])
        rows = self.get_serializer(merits, many=True).data
        if not many:
            return Response(rows[0], status=201)
        return Response({"awarded": len(merits), "merits": rows}, status=201)

    def _check_can_edit(self, merit):
        user = self.request.user
        if not (is_leader(user) or merit.awarded_by_id == user.id):
            raise PermissionDenied("Only the person who gave this merit, leadership or an admin can change it.")

    def partial_update(self, request, *args, **kwargs):
        merit = self.get_object()
        self._check_can_edit(merit)
        data = {k: v for k, v in request.data.items() if k in MERIT_EDITABLE}
        serializer = self.get_serializer(merit, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self._check_date(serializer, merit.school)
        merit = serializer.save()
        log_activity(school=merit.school, actor=request.user, action="discipline.merit_updated", target=merit.student,
                     summary=f"Updated a merit for {student_name(merit.student)}")
        return Response(self.get_serializer(merit).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        merit = self.get_object()
        self._check_can_edit(merit)
        student = merit.student
        summary = (f"Removed a merit for {student_name(student)} "
                   f"({merit.get_category_display()}, {merit.date.isoformat()})")
        merit.delete()
        log_activity(school=student.school, actor=request.user, action="discipline.merit_removed", target=student,
                     summary=summary)
        return Response(status=204)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        Points for the merits matching the same filters: the total, the top
        students (up to 10) and each class's points.
        """
        merits = self.get_queryset().order_by()
        top = (merits.values("student").annotate(points=Sum("points"), merits=Count("id"))
               .order_by("-points", "student")[:10])
        names = {s.id: s for s in visible_students(request.user).filter(pk__in=[t["student"] for t in top])
                 .select_related("school_class")}
        classes = (merits.exclude(student__school_class=None)
                   .values("student__school_class", "student__school_class__name")
                   .annotate(points=Sum("points"), merits=Count("id"), students=Count("student", distinct=True))
                   .order_by("-points", "student__school_class__name"))
        totals = merits.aggregate(points=Sum("points"), merits=Count("id"), students=Count("student", distinct=True))
        return Response({
            "points": totals["points"] or 0, "merits": totals["merits"], "students": totals["students"],
            "top_students": [{
                "id": t["student"], "name": student_name(names[t["student"]]),
                "class_name": names[t["student"]].school_class.name if names[t["student"]].school_class else None,
                "points": t["points"], "merits": t["merits"],
            } for t in top],
            "classes": [{"id": c["student__school_class"], "name": c["student__school_class__name"],
                         "points": c["points"], "merits": c["merits"], "students": c["students"]} for c in classes],
        })

    @action(detail=False, methods=["get"])
    def choices(self, request):
        return Response({"categories": Merit.Category.choices, "max_points": Merit.MAX_POINTS})
