from django.db import transaction
from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response

from accounts.scoping import is_admin
from activity.services import display_name, log_activity, student_name
from students.localtime import school_localdate
from students.models import Student

from . import services
from .models import Absence, Bed, Dorm, LeaveRequest, RollCall, RollCallEntry, SickBayVisit
from .serializers import (AbsenceSerializer, BoardingHouseSerializer, DormSerializer, LeaveRequestSerializer,
                          RollCallSerializer, SickBayVisitSerializer, boarder_row)


class BoardingStaff(BasePermission):
    message = "Only boarding staff (a house's staff, or admins) can do this, at a school with boarding turned on."

    def has_permission(self, request, view):
        return services.is_boarding_staff(request.user)


class AdminWrites(BasePermission):
    message = "Only admins can change houses, dormitories and beds."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or is_admin(request.user)


def _boarder(user, student_id):
    """A boarder in one of the user's houses, or 404."""
    student = services.boarders(user).filter(pk=student_id).first() if str(student_id).isdigit() else None
    if student is None:
        raise ValidationError({"student": ["Choose a boarder in one of your houses."]})
    return student


def _log(request, action_name, student, summary):
    log_activity(school=request.user.profile.school, actor=request.user, action=action_name, target=student,
                 summary=summary)


class HouseViewSet(viewsets.ModelViewSet):
    """Boarding houses, each with its staff, dormitories and beds."""

    serializer_class = BoardingHouseSerializer
    permission_classes = [IsAuthenticated, BoardingStaff, AdminWrites]

    def get_permissions(self):
        # Admins set up houses before anyone is boarding staff (once the school has turned boarding on).
        if is_admin(self.request.user) and self.request.user.profile.school.has_boarding:
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        return services.houses_for(self.request.user).prefetch_related("staff__user", "dorms")

    def perform_create(self, serializer):
        serializer.save(school=self.request.user.profile.school)


class DormViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin,
                  viewsets.GenericViewSet):
    """Admins: add, rename or remove dormitories; POST beds/ {count} adds beds."""

    serializer_class = DormSerializer
    permission_classes = [IsAuthenticated, AdminWrites]

    def get_queryset(self):
        return Dorm.objects.filter(house__school=self.request.user.profile.school)

    @action(detail=True, methods=["post"])
    def beds(self, request, pk=None):
        dorm = self.get_object()
        try:
            count = int(request.data.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        if not 1 <= count <= 100:
            raise ValidationError({"count": ["Add between 1 and 100 beds."]})
        start = dorm.beds.count()
        Bed.objects.bulk_create([Bed(dorm=dorm, name=f"Bed {start + n}") for n in range(1, count + 1)])
        return Response(BoardingHouseSerializer(dorm.house, context={"request": request}).data, status=201)


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated, BoardingStaff])
def bed(request, pk):
    """POST {student: id or null}: put a boarder in this bed (or empty it). DELETE removes an empty bed (admins)."""
    found = Bed.objects.filter(pk=pk, dorm__house__in=services.houses_for(request.user)).select_related(
        "dorm__house").first()
    if found is None:
        raise NotFound("Bed not found.")
    if request.method == "DELETE":
        if not is_admin(request.user):
            raise PermissionDenied("Only admins can remove beds.")
        if found.student_id:
            raise ValidationError("Move the boarder out of this bed first.")
        found.delete()
        return Response(status=204)
    student_id = request.data.get("student")
    with transaction.atomic():
        if student_id in (None, ""):
            previous = found.student
            found.student = None
            found.save(update_fields=["student"])
            if previous:
                _log(request, "boarding.bed", previous, f"Took {student_name(previous)} out of "
                                                        f"{found.dorm.house.name} {found} ")
            return Response({"bed": found.id, "student": None})
        student = Student.objects.filter(pk=student_id, school=request.user.profile.school, is_active=True).first() \
            if str(student_id).isdigit() else None
        if student is None:
            raise ValidationError({"student": ["Choose a current student."]})
        Bed.objects.filter(student=student).update(student=None)  # moving beds
        found.student = student
        found.save(update_fields=["student"])
        if student.mode_of_learning != "boarding":
            Student.objects.filter(pk=student.pk).update(mode_of_learning="boarding")
    _log(request, "boarding.bed", student, f"Put {student_name(student)} in {found.dorm.house.name} {found}")
    return Response({"bed": found.id, "student": student.id})


@api_view(["GET"])
@permission_classes([IsAuthenticated, BoardingStaff])
def boarders(request):
    """The boarders in the user's houses (?house=), with where they are now: in, on leave or in sick bay."""
    students = list(services.boarders(request.user, request.query_params.get("house") or None)
                    .order_by("bed__dorm__house__name", "bed__dorm__name", "last_name", "first_name"))
    away = services.where_now([s.id for s in students])
    return Response([boarder_row(s, away) for s in students])


@api_view(["GET"])
@permission_classes([IsAuthenticated, BoardingStaff])
def student_search(request):
    """?q=: current students to put in a bed (name or admission number), at most 20."""
    q = (request.query_params.get("q") or "").strip()
    students = Student.objects.filter(school=request.user.profile.school, is_active=True)
    for word in q.split():
        students = students.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word) |
                                   Q(external_id__icontains=word))
    return Response([{"id": s.id, "name": f"{s.first_name} {s.last_name}",
                      "class_name": s.school_class.name if s.school_class else "",
                      "bed": f"{s.bed.dorm.house.name} {s.bed}" if hasattr(s, "bed") else ""}
                     for s in students.select_related("school_class", "bed__dorm__house")
                     .order_by("last_name", "first_name")[:20]])


@api_view(["GET"])
@permission_classes([IsAuthenticated, BoardingStaff])
def overview(request):
    return Response(services.overview(request.user))


class RollCallViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                      viewsets.GenericViewSet):
    """POST {house, session, date?} opens (or reopens) a roll call; POST <id>/mark/ {entries, complete}."""

    serializer_class = RollCallSerializer
    permission_classes = [IsAuthenticated, BoardingStaff]

    def get_queryset(self):
        queryset = RollCall.objects.filter(house__in=services.houses_for(self.request.user)).select_related("house")
        if house := self.request.query_params.get("house"):
            queryset = queryset.filter(house_id=house)
        return queryset

    def create(self, request, *args, **kwargs):
        house = services.houses_for(request.user).filter(pk=request.data.get("house")).first() \
            if str(request.data.get("house", "")).isdigit() else None
        if house is None:
            raise ValidationError({"house": ["Choose one of your houses."]})
        session = request.data.get("session")
        if session not in RollCall.Session.values:
            raise ValidationError({"session": ["Choose morning, evening or night."]})
        roll_call = services.start_roll_call(house, request.data.get("date") or school_localdate(house.school),
                                             session, request.user)
        return Response(self.get_serializer(roll_call).data, status=201)

    @action(detail=True, methods=["post"])
    def mark(self, request, pk=None):
        roll_call = self.get_object()
        entries = request.data.get("entries") or []
        statuses = set(RollCallEntry.Status.values) | {""}
        rows = {e.student_id: e for e in roll_call.entries.all()}
        changed = []
        for item in entries:
            entry = rows.get(item.get("student")) if isinstance(item, dict) else None
            if entry is None or item.get("status", entry.status) not in statuses:
                raise ValidationError({"entries": ["Each entry needs a boarder on this roll call and a valid status."]})
            entry.status = item.get("status", entry.status)
            entry.note = str(item.get("note", entry.note))[:300]
            changed.append(entry)
        RollCallEntry.objects.bulk_update(changed, ["status", "note"])
        if request.data.get("complete"):
            if roll_call.entries.filter(status="").exists():
                raise ValidationError("Mark every boarder before finishing the roll call.")
            with transaction.atomic():
                roll_call.completed_at = services.now()
                roll_call.save(update_fields=["completed_at"])
                services.open_absences_from(roll_call, request.user)
            missing = roll_call.entries.filter(status=RollCallEntry.Status.MISSING).count()
            log_activity(school=roll_call.house.school, actor=request.user, action="boarding.roll_call",
                         summary=f"{roll_call.house.name} {roll_call.get_session_display().lower()} roll call: "
                                 f"{missing} missing")
        return Response(self.get_serializer(roll_call).data)


class AbsenceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Boarders who were marked missing. ?status=open (default), resolved or all. POST <id>/resolve/
    {resolution, note} closes one: only a person does that, never a later roll call."""

    serializer_class = AbsenceSerializer
    permission_classes = [IsAuthenticated, BoardingStaff]

    def get_queryset(self):
        queryset = Absence.objects.filter(house__in=services.houses_for(self.request.user)) \
            .select_related("student", "house", "roll_call")
        status = self.request.query_params.get("status", "open" if self.action == "list" else "all")
        if status in ("open", "resolved"):
            queryset = queryset.filter(status=status)
        if student := self.request.query_params.get("student"):
            queryset = queryset.filter(student_id=student)
        return queryset

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        absence = self.get_object()
        if absence.status != Absence.Status.OPEN:
            raise ValidationError("This absence is already resolved.")
        resolution = request.data.get("resolution")
        allowed = [Absence.Resolution.FOUND, Absence.Resolution.RETURNED, Absence.Resolution.ON_LEAVE,
                   Absence.Resolution.LEFT_SCHOOL]
        if resolution not in allowed:
            raise ValidationError({"resolution": ["Choose found, returned, on authorised leave or left the school."]})
        services.resolve_absence(absence, resolution, request.user, str(request.data.get("note", "")))
        return Response(self.get_serializer(absence).data)


class LeaveViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                   viewsets.GenericViewSet):
    """Leave and exeat. Staff-made leave is approved straight away; parents' requests wait for a decision."""

    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated, BoardingStaff]

    def get_queryset(self):
        queryset = LeaveRequest.objects.filter(student__in=services.boarders(self.request.user)) \
            .select_related("student__bed__dorm__house")
        if status := self.request.query_params.get("status"):
            queryset = queryset.filter(status__in=status.split(","))
        if student := self.request.query_params.get("student"):
            queryset = queryset.filter(student_id=student)
        return queryset

    def perform_create(self, serializer):
        student = _boarder(self.request.user, self.request.data.get("student"))
        user = self.request.user
        leave = serializer.save(school=student.school, student=student, status=LeaveRequest.Status.APPROVED,
                                requested_by=user, requested_by_name=display_name(user),
                                decided_by_name=display_name(user), decided_at=services.now())
        _log(self.request, "boarding.leave", student, f"Gave {student_name(student)} {leave.get_kind_display().lower()}"
                                                      f" leave")
        services.email_parents(student, f"Leave for {student.first_name}",
                               f"{student.school.name} has recorded {leave.get_kind_display().lower()} leave for "
                               f"{student.first_name}. The dates are in HouseMaster.")

    def _move(self, request, allowed, to, verb, **fields):
        leave = self.get_object()
        if leave.status not in allowed:
            raise ValidationError(f"This leave is {leave.get_status_display().lower()}, so it can't be {verb}.")
        leave.status = to
        for key, value in fields.items():
            setattr(leave, key, value)
        leave.save()
        _log(request, "boarding.leave", leave.student, f"{verb.capitalize()} {student_name(leave.student)}'s "
                                                       f"{leave.get_kind_display().lower()} leave")
        return leave

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        leave = self._move(request, ["requested"], "approved", "approved", decided_by_name=display_name(request.user),
                           decided_at=services.now(), decision_note=str(request.data.get("note", ""))[:1000])
        services.email_parents(leave.student, f"Leave approved for {leave.student.first_name}",
                               f"The leave you asked for {leave.student.first_name} has been approved.")
        return Response(self.get_serializer(leave).data)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        leave = self._move(request, ["requested", "approved"], "declined", "declined",
                           decided_by_name=display_name(request.user), decided_at=services.now(),
                           decision_note=str(request.data.get("note", ""))[:1000])
        services.email_parents(leave.student, f"Leave for {leave.student.first_name}",
                               f"The leave you asked for {leave.student.first_name} hasn't been approved. "
                               "The boarding staff's note is in HouseMaster.")
        return Response(self.get_serializer(leave).data)

    @action(detail=True, methods=["post"], url_path="sign-out")
    def sign_out(self, request, pk=None):
        leave = self._move(request, ["approved"], "out", "signed out", signed_out_at=services.now(),
                           signed_out_by_name=display_name(request.user))
        return Response(self.get_serializer(leave).data)

    @action(detail=True, methods=["post"], url_path="sign-in")
    def sign_in(self, request, pk=None):
        leave = self._move(request, ["out"], "returned", "signed back in", signed_in_at=services.now(),
                           signed_in_by_name=display_name(request.user))
        return Response(self.get_serializer(leave).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        leave = self._move(request, ["requested", "approved"], "cancelled", "cancelled")
        return Response(self.get_serializer(leave).data)


class SickBayViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                     mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Sick bay: check a boarder in (optionally emailing parents), note treatment, check out with an outcome."""

    serializer_class = SickBayVisitSerializer
    permission_classes = [IsAuthenticated, BoardingStaff]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = SickBayVisit.objects.filter(student__in=services.boarders(self.request.user)) \
            .select_related("student")
        if self.request.query_params.get("open"):
            queryset = queryset.filter(checked_out_at__isnull=True)
        if student := self.request.query_params.get("student"):
            queryset = queryset.filter(student_id=student)
        return queryset

    def perform_create(self, serializer):
        student = _boarder(self.request.user, self.request.data.get("student"))
        if SickBayVisit.objects.filter(student=student, checked_out_at__isnull=True).exists():
            raise ValidationError({"student": [f"{student_name(student)} is already in sick bay."]})
        visit = serializer.save(school=student.school, student=student,
                                checked_in_at=serializer.validated_data.get("checked_in_at") or services.now(),
                                checked_in_by_name=display_name(self.request.user))
        _log(self.request, "boarding.sick_bay", student, f"Checked {student_name(student)} into sick bay")
        if self.request.data.get("tell_parents"):
            self._tell(visit)

    def _tell(self, visit):
        sent = services.email_parents(visit.student, f"{visit.student.first_name} visited the sick bay",
                                      f"{visit.student.first_name} visited the school sick bay today. What happened "
                                      "and what was given is in HouseMaster.")
        if sent:
            visit.parents_told_at = services.now()
            visit.parents_told_how = "Emailed through HouseMaster"
            visit.save(update_fields=["parents_told_at", "parents_told_how"])

    @action(detail=True, methods=["post"])
    def told(self, request, pk=None):
        """{how: "phoned mother"} records telling parents another way; with {email: true}, emails them."""
        visit = self.get_object()
        if request.data.get("email"):
            self._tell(visit)
        else:
            visit.parents_told_at = services.now()
            visit.parents_told_how = str(request.data.get("how", "")).strip()[:200] or "Told"
            visit.save(update_fields=["parents_told_at", "parents_told_how"])
        return Response(self.get_serializer(visit).data)

    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out(self, request, pk=None):
        visit = self.get_object()
        if visit.checked_out_at:
            raise ValidationError("Already checked out.")
        outcome = request.data.get("outcome")
        if outcome not in SickBayVisit.Outcome.values:
            raise ValidationError({"outcome": ["Choose where they went."]})
        visit.outcome = outcome
        visit.treatment = str(request.data.get("treatment", visit.treatment))
        visit.checked_out_at = services.now()
        visit.checked_out_by_name = display_name(request.user)
        visit.save()
        _log(request, "boarding.sick_bay", visit.student, f"Checked {student_name(visit.student)} out of sick bay "
                                                          f"({visit.get_outcome_display().lower()})")
        return Response(self.get_serializer(visit).data)


# --- parents (wired through guardians.views.GuardianStudentViewSet) ---

def guardian_boarding(student):
    """A parent's view: bed, leave and sick bay visits (no staff-only names beyond who decided)."""
    bed = getattr(student, "bed", None)
    if bed is None or not student.school.has_boarding:
        return {"boarder": False}
    away = services.where_now([student.id])
    return {
        "boarder": True, "house": bed.dorm.house.name, "dorm": bed.dorm.name, "bed": bed.name,
        "where": away.get(student.id, "in"),
        "leave": [{k: v for k, v in LeaveRequestSerializer(leave).data.items() if k not in ("requested_by_name",)}
                  for leave in student.leave_requests.all()[:20]],
        "sick_bay": [{k: v for k, v in SickBayVisitSerializer(v).data.items()
                      if k in ("id", "checked_in_at", "complaint", "treatment", "checked_out_at", "outcome",
                               "outcome_label")} for v in student.sick_bay_visits.all()[:20]],
    }


def guardian_request_leave(request, student):
    """A parent asks for leave; it waits for boarding staff."""
    if not hasattr(student, "bed") or not student.school.has_boarding:
        raise ValidationError("Only boarders need leave.")
    serializer = LeaveRequestSerializer(data={**request.data, "student": student.id})
    serializer.is_valid(raise_exception=True)
    leave = serializer.save(school=student.school, student=student, requested_by=request.user,
                            requested_by_name=request.user.guardian.name)
    log_activity(school=student.school, actor=request.user, action="boarding.leave", target=student,
                 summary=f"A parent asked for {leave.get_kind_display().lower()} leave for {student_name(student)}")
    return LeaveRequestSerializer(leave).data


def guardian_cancel_leave(request, student, leave_id):
    leave = student.leave_requests.filter(pk=leave_id, status__in=["requested", "approved"]).first()
    if leave is None:
        raise NotFound("No leave to cancel.")
    leave.status = LeaveRequest.Status.CANCELLED
    leave.save(update_fields=["status"])
    return LeaveRequestSerializer(leave).data
