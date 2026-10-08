from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Profile
from accounts.permissions import HasSchoolProfile
from accounts.scoping import RECORDS, is_leader, scope_class_ids, visible_students
from activity.services import display_name, log_activity, student_name
from students.localtime import school_localdate
from students.models import Student

from .models import Club, ClubAttendance, ClubMember, ClubSession, Fixture
from .serializers import ClubSerializer, FixtureSerializer
from .services import attendance_counts, can_manage

CLUB_FIELDS = ("name", "kind", "description", "meets", "location", "is_active")
FIXTURE_FIELDS = ("date", "start_time", "opponent", "venue", "location", "competition", "team", "our_score",
                  "their_score", "result_note", "report")
MAX_AT_ONCE = 200


def _day(value, field="date"):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError({field: ["Use a date like 2026-10-08."]})


def _ids(values, field):
    if not isinstance(values, list):
        raise ValidationError({field: ["Send a list."]})
    if len(values) > MAX_AT_ONCE:
        raise ValidationError({field: [f"At most {MAX_AT_ONCE} at a time."]})
    try:
        return {int(v) for v in values}
    except (TypeError, ValueError):
        raise ValidationError({field: ["Student not found."]})


def _visible_ids(user):
    """None when this person sees every student's records; otherwise the ids they may see."""
    if scope_class_ids(user, RECORDS) is None:
        return None
    return set(visible_students(user, RECORDS).values_list("id", flat=True))


def _student_row(student):
    return {"student": student.id, "name": student_name(student),
            "class_name": student.school_class.name if student.school_class_id else None}


class ClubViewSet(viewsets.ModelViewSet):
    """
    Clubs, teams and societies. Every staff member sees the list (?mine=1
    for the ones they run). Leadership and admins add, rename and remove
    clubs and choose their staff (POST/PATCH {name, kind, description,
    meets, location, is_active, leaders: [user ids]}); a club's staff may
    change its other details. Members, registers and fixtures are run by
    the club's staff, leadership and admins.
    """

    serializer_class = ClubSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = (Club.objects.filter(school=user.profile.school).prefetch_related("leaders__profile")
                    .annotate(member_count=Count("members", filter=Q(members__student__is_active=True), distinct=True)))
        if self.request.query_params.get("mine"):
            queryset = queryset.filter(leaders=user)
        return queryset

    def _club(self, require_manage=True):
        club = self.get_object()
        if require_manage and not can_manage(self.request.user, club):
            raise PermissionDenied("Only the club's staff, leadership or an admin can do this.")
        return club

    def _set_leaders(self, club, ids):
        ids = _ids(ids, "leaders")
        staff = list(get_user_model().objects.filter(
            pk__in=ids, is_active=True, profile__school=club.school).exclude(profile__role=Profile.Role.GOVERNOR))
        if len(staff) != len(ids):
            raise ValidationError({"leaders": ["Choose staff from your school."]})
        club.leaders.set(staff)

    def create(self, request, *args, **kwargs):
        user = request.user
        if not is_leader(user):
            raise PermissionDenied("Only leadership or an admin can add a club.")
        serializer = self.get_serializer(data={k: v for k, v in request.data.items() if k in CLUB_FIELDS})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            club = serializer.save(school=user.profile.school)
            if "leaders" in request.data:
                self._set_leaders(club, request.data["leaders"])
        log_activity(school=club.school, actor=user, action="clubs.created", target=club, summary=f"Added the club {club.name}")
        return Response(self.get_serializer(self.get_queryset().get(pk=club.pk)).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        club = self._club()
        user = request.user
        if "leaders" in request.data and not is_leader(user):
            raise PermissionDenied("Only leadership or an admin can choose a club's staff.")
        serializer = self.get_serializer(club, data={k: v for k, v in request.data.items() if k in CLUB_FIELDS}, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            club = serializer.save()
            if "leaders" in request.data:
                self._set_leaders(club, request.data["leaders"])
        log_activity(school=club.school, actor=user, action="clubs.updated", target=club, summary=f"Updated the club {club.name}")
        return Response(self.get_serializer(self.get_queryset().get(pk=club.pk)).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        club = self.get_object()
        if not is_leader(request.user):
            raise PermissionDenied("Only leadership or an admin can remove a club.")
        name = club.name
        club.delete()
        log_activity(school=request.user.profile.school, actor=request.user, action="clubs.deleted",
                     summary=f"Removed the club {name} with its members, registers and fixtures")
        return Response(status=204)

    @action(detail=False, methods=["get"])
    def staff(self, request):
        """The staff a club can be given (leadership and admins)."""
        if not is_leader(request.user):
            raise PermissionDenied("Only leadership or an admin can choose a club's staff.")
        profiles = (Profile.objects.filter(school=request.user.profile.school, user__is_active=True)
                    .exclude(role=Profile.Role.GOVERNOR).select_related("user"))
        return Response(sorted(({"id": p.user_id, "name": p.name} for p in profiles), key=lambda r: r["name"].lower()))

    @action(detail=False, methods=["get"])
    def choices(self, request):
        return Response({"kinds": Club.Kind.choices, "venues": Fixture.Venue.choices,
                         "statuses": ClubAttendance.Status.choices})

    # Members ---------------------------------------------------------------

    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        """
        GET: the members (the club's staff see everyone; other staff only the
        students they can see), each with their attendance. POST {students:
        [ids], role?}: add active students from the school.
        """
        if request.method == "POST":
            return self._add_members(request)
        club = self._club(require_manage=False)
        manage = can_manage(request.user, club)
        rows = club.members.filter(student__is_active=True).select_related("student__school_class")
        if not manage:
            visible = _visible_ids(request.user)
            if visible is not None:
                rows = rows.filter(student_id__in=visible)
        rows = list(rows)
        counts = attendance_counts(club, [m.student_id for m in rows])
        blank = {"present": 0, "absent": 0, "excused": 0, "sessions": 0}
        return Response([{**_student_row(m.student), "role": m.role, "joined_on": m.joined_on,
                          "attendance": counts.get(m.student_id, blank)} for m in rows])

    def _add_members(self, request):
        club = self._club()
        ids = _ids(request.data.get("students"), "students")
        if not ids:
            raise ValidationError({"students": ["Choose at least one student."]})
        students = list(Student.objects.filter(school=club.school, pk__in=ids, is_active=True))
        if len(students) != len(ids):
            raise ValidationError({"students": ["Student not found."]})
        role = str(request.data.get("role", "")).strip()[:60]
        today = school_localdate(club.school)
        existing = set(club.members.values_list("student_id", flat=True))
        added = [s for s in students if s.id not in existing]
        ClubMember.objects.bulk_create([ClubMember(club=club, student=s, role=role, joined_on=today) for s in added])
        if added:
            who = student_name(added[0]) if len(added) == 1 else f"{len(added)} students"
            log_activity(school=club.school, actor=request.user, action="clubs.members_added", target=club,
                         summary=f"Added {who} to {club.name}", students=[s.id for s in added])
        return Response({"added": len(added), "already": len(students) - len(added)}, status=201)

    @action(detail=True, methods=["patch", "delete"], url_path=r"members/(?P<student_id>[0-9]+)")
    def member(self, request, pk=None, student_id=None):
        """PATCH {role}: e.g. make them captain. DELETE: take them out of the club (their registers stay)."""
        club = self._club()
        try:
            membership = club.members.select_related("student").get(student_id=student_id)
        except ClubMember.DoesNotExist:
            raise ValidationError({"student": ["They aren't in this club."]})
        name = student_name(membership.student)
        if request.method == "DELETE":
            membership.delete()
            # Out of the squad for fixtures still to come; past squads stay as they were.
            Fixture.players.through.objects.filter(
                fixture__club=club, fixture__date__gte=school_localdate(club.school), student_id=student_id).delete()
            log_activity(school=club.school, actor=request.user, action="clubs.member_removed", target=club,
                         summary=f"Took {name} out of {club.name}")
            return Response(status=204)
        membership.role = str(request.data.get("role", "")).strip()[:60]
        membership.save(update_fields=["role"])
        log_activity(school=club.school, actor=request.user, action="clubs.member_updated", target=club,
                     summary=f"Changed {name}'s role in {club.name}")
        return Response({**_student_row(membership.student), "role": membership.role, "joined_on": membership.joined_on})

    @action(detail=True, methods=["get"])
    def candidates(self, request, pk=None):
        """?q= (2+ letters): up to 20 active students from the school who aren't in the club yet."""
        club = self._club()
        q = request.query_params.get("q", "").strip()
        if len(q) < 2:
            return Response([])
        found = Student.objects.filter(school=club.school, is_active=True).exclude(club_memberships__club=club)
        for word in q.split()[:3]:
            found = found.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word) | Q(external_id__icontains=word))
        found = found.select_related("school_class").order_by("last_name", "first_name")[:20]
        return Response([{**_student_row(s), "external_id": s.external_id} for s in found])

    # Registers -------------------------------------------------------------

    @action(detail=True, methods=["get", "post"])
    def register(self, request, pk=None):
        """
        GET ?date=: the register for that day (members, and anyone already
        marked). POST {date, note?, marks: [{student, status}]}: save it.
        """
        club = self._club()
        when = _day(request.data.get("date") if request.method == "POST" else
                    request.query_params.get("date") or school_localdate(club.school).isoformat())
        if when > school_localdate(club.school):
            raise ValidationError({"date": ["The date can't be in the future."]})
        if request.method == "POST":
            self._save_register(request, club, when)
        session = club.sessions.filter(date=when).first()
        marks = {m.student_id: m.status for m in session.marks.all()} if session else {}
        members = {m.student_id: m for m in club.members.filter(student__is_active=True).select_related("student__school_class")}
        extra = Student.objects.filter(pk__in=set(marks) - set(members)).select_related("school_class")
        rows = [{**_student_row(m.student), "role": m.role, "status": marks.get(sid)} for sid, m in members.items()]
        rows += [{**_student_row(s), "role": "", "status": marks.get(s.id), "left": True} for s in extra]
        rows.sort(key=lambda r: r["name"].split(" ")[-1].lower() + r["name"].lower())
        return Response({"date": when, "taken": session is not None,
                         "note": session.note if session else "", "taken_by_name": session.taken_by_name if session else "",
                         "students": rows})

    def _save_register(self, request, club, when):
        marks = request.data.get("marks")
        if not isinstance(marks, list) or not marks:
            raise ValidationError({"marks": ["Mark at least one student."]})
        members = set(club.members.values_list("student_id", flat=True))
        statuses = {}
        for mark in marks:
            try:
                sid = int(mark.get("student"))
            except (AttributeError, TypeError, ValueError):
                raise ValidationError({"marks": ["Student not found."]})
            if sid not in members:
                raise ValidationError({"marks": ["Only the club's members can be marked."]})
            if mark.get("status") not in ClubAttendance.Status.values:
                raise ValidationError({"marks": ["Mark each student present, absent or excused."]})
            statuses[sid] = mark["status"]
        with transaction.atomic():
            session, _ = ClubSession.objects.update_or_create(
                club=club, date=when, defaults={"note": str(request.data.get("note", ""))[:300],
                                                "taken_by_name": display_name(request.user)})
            for sid, status in statuses.items():
                ClubAttendance.objects.update_or_create(session=session, student_id=sid, defaults={"status": status})
        present = sum(1 for s in statuses.values() if s == "present")
        log_activity(school=club.school, actor=request.user, action="clubs.register_taken", target=club,
                     summary=f"Took the {club.name} register for {when.isoformat()} ({present} of {len(statuses)} present)")

    @action(detail=True, methods=["get"])
    def sessions(self, request, pk=None):
        """The club's last 50 registers with how many came."""
        club = self._club()
        rows = (club.sessions.annotate(present=Count("marks", filter=Q(marks__status="present")),
                                       absent=Count("marks", filter=Q(marks__status="absent")),
                                       excused=Count("marks", filter=Q(marks__status="excused")))[:50])
        return Response([{"id": s.id, "date": s.date, "note": s.note, "taken_by_name": s.taken_by_name,
                          "present": s.present, "absent": s.absent, "excused": s.excused} for s in rows])


class FixtureViewSet(viewsets.ModelViewSet):
    """
    Fixtures and results for every club: every staff member sees them;
    the club's staff, leadership and admins add and change them. POST/PATCH
    {club (create only), date, start_time, opponent, venue, location,
    competition, team, our_score, their_score, result_note, report,
    players: [member ids]}. Filter with ?club=, ?upcoming=1 (today on,
    soonest first, no result yet), ?results=1 (with a result, latest first),
    ?from=, ?to=.
    """

    serializer_class = FixtureSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        school = user.profile.school
        queryset = (Fixture.objects.filter(club__school=school)
                    .select_related("club").prefetch_related("club__leaders", "players"))
        params = self.request.query_params
        if params.get("club"):
            queryset = queryset.filter(club_id=params["club"])
        for param, lookup in (("from", "date__gte"), ("to", "date__lte")):
            if params.get(param):
                queryset = queryset.filter(**{lookup: _day(params[param], param)})
        today = school_localdate(school)
        if params.get("upcoming"):  # still to be played: today on, no result yet
            queryset = queryset.filter(date__gte=today, our_score__isnull=True, result_note="")
        if params.get("results"):
            queryset = (queryset.filter(Q(our_score__isnull=False) | ~Q(result_note=""))
                        .order_by("-date", "-start_time", "-id"))
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if hasattr(self.request.user, "profile"):
            context["visible_ids"] = _visible_ids(self.request.user)
        return context

    def _check(self, club):
        if not can_manage(self.request.user, club):
            raise PermissionDenied("Only the club's staff, leadership or an admin can do this.")

    def _set_players(self, fixture, ids):
        ids = _ids(ids, "players")
        members = set(fixture.club.members.filter(student__is_active=True).values_list("student_id", flat=True))
        if not ids <= members:
            raise ValidationError({"players": ["Only the club's members can be picked."]})
        fixture.players.set(ids)

    def create(self, request, *args, **kwargs):
        try:
            club = Club.objects.get(pk=request.data.get("club"), school=request.user.profile.school)
        except (Club.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"club": ["Club not found."]})
        self._check(club)
        serializer = self.get_serializer(data={k: v for k, v in request.data.items() if k in FIXTURE_FIELDS})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            fixture = serializer.save(club=club)
            if "players" in request.data:
                self._set_players(fixture, request.data["players"])
        log_activity(school=club.school, actor=request.user, action="clubs.fixture_added", target=club,
                     summary=f"Added {club.name} v {fixture.opponent} on {fixture.date.isoformat()}")
        return Response(self.get_serializer(fixture).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        fixture = self.get_object()
        self._check(fixture.club)
        had_result = fixture.has_result
        serializer = self.get_serializer(fixture, data={k: v for k, v in request.data.items() if k in FIXTURE_FIELDS},
                                         partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            fixture = serializer.save()
            if "players" in request.data:
                self._set_players(fixture, request.data["players"])
        what = "the result of" if fixture.has_result and not had_result else "the fixture"
        log_activity(school=fixture.club.school, actor=request.user, action="clubs.fixture_updated", target=fixture.club,
                     summary=f"Updated {what} {fixture.club.name} v {fixture.opponent} ({fixture.date.isoformat()})")
        return Response(self.get_serializer(fixture).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        fixture = self.get_object()
        club = fixture.club
        self._check(club)
        summary = f"Removed {club.name} v {fixture.opponent} ({fixture.date.isoformat()})"
        fixture.delete()
        log_activity(school=club.school, actor=request.user, action="clubs.fixture_removed", target=club, summary=summary)
        return Response(status=204)
