from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response

from accounts.models import Profile
from accounts.permissions import HasSchoolProfile
from accounts.scoping import visible_students
from activity.services import log_activity
from students.localtime import school_localdate
from students.models import SchoolClass

from . import services
from .models import Lesson, Period, Room, SchoolWeek
from .serializers import LessonSerializer, PeriodSerializer, RoomSerializer


class AdminWritesStaffReads(BasePermission):
    message = "Only admins can change the timetable."

    def has_permission(self, request, view):
        profile = getattr(request.user, "profile", None)
        return profile is not None and (request.method in SAFE_METHODS or profile.is_admin)


class _SchoolScoped(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, AdminWritesStaffReads]
    model = None

    def get_queryset(self):
        return self.model.objects.filter(school=self.request.user.profile.school)

    def perform_create(self, serializer):
        serializer.save(school=self.request.user.profile.school)


class PeriodViewSet(_SchoolScoped):
    """The periods of the school day. POST standard/ replaces them with a regular day (before any lessons)."""

    model = Period
    serializer_class = PeriodSerializer

    @action(detail=False, methods=["post"])
    def standard(self, request):
        data = request.data
        try:
            services.standard_day(request.user.profile.school, start=data.get("start") or "08:00",
                                  lesson_minutes=data.get("lesson_minutes") or 40, lessons=data.get("lessons") or 8,
                                  breaks=data.get("breaks") or [])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValidationError(str(exc) if isinstance(exc, ValueError) else "Check the times and numbers.")
        return Response(PeriodSerializer(self.get_queryset(), many=True).data, status=201)


class RoomViewSet(_SchoolScoped):
    model = Room
    serializer_class = RoomSerializer


class LessonViewSet(_SchoolScoped):
    """Lessons; filter with ?school_class=, ?teacher=, ?room=, ?day=."""

    model = Lesson
    serializer_class = LessonSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("school_class", "subject", "teacher", "room", "period")
        for field in ("school_class", "teacher", "room", "day"):
            if value := self.request.query_params.get(field):
                queryset = queryset.filter(**{field: value})
        return queryset

    def perform_create(self, serializer):
        lesson = serializer.save(school=self.request.user.profile.school)
        self._log("added", lesson)

    def perform_update(self, serializer):
        self._log("changed", serializer.save())

    def perform_destroy(self, instance):
        self._log("removed", instance)
        instance.delete()

    def _log(self, verb, lesson):
        log_activity(school=lesson.school, actor=self.request.user, action="timetable.changed",
                     summary=f"Timetable: {verb} {lesson.school_class.name} {lesson.label} "
                             f"({services.DAY_NAMES[lesson.day]} {lesson.period.name})")


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, AdminWritesStaffReads])
def school_week(request):
    """GET: the teaching days; PATCH {days: [1, 2, 3, 4, 5]} (admins)."""
    school = request.user.profile.school
    week, _ = SchoolWeek.objects.get_or_create(school=school)
    if request.method == "PATCH":
        days = request.data.get("days")
        if not isinstance(days, list) or not days or any(d not in range(1, 8) for d in days):
            raise ValidationError({"days": ["Choose at least one day."]})
        if Lesson.objects.filter(school=school).exclude(day__in=days).exists():
            raise ValidationError({"days": ["Some lessons are on a day you're removing. Move them first."]})
        week.days = "".join(str(d) for d in sorted(set(days)))
        week.save()
    return Response({"days": week.day_numbers()})


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def week_view(request):
    """A week grid for ?school_class=, ?teacher=, ?room= or ?student=; with none of them, the viewer's own."""
    school = request.user.profile.school
    params = request.query_params
    lessons = Lesson.objects.filter(school=school)
    if value := params.get("school_class"):
        klass = get_object_or_404(SchoolClass, pk=value, year_group__school=school)
        lessons, title = lessons.filter(school_class=klass), klass.name
    elif value := params.get("teacher"):
        teacher = get_object_or_404(Profile, pk=value, school=school)
        lessons, title = lessons.filter(teacher=teacher), teacher.name
    elif value := params.get("room"):
        room = get_object_or_404(Room, pk=value, school=school)
        lessons, title = lessons.filter(room=room), room.name
    elif value := params.get("student"):
        student = visible_students(request.user).filter(pk=value).first() if str(value).isdigit() else None
        if student is None:
            raise NotFound("Student not found.")
        lessons, title = services.student_lessons(student), f"{student.first_name} {student.last_name}"
    else:
        lessons, title = lessons.filter(teacher=request.user.profile), "My timetable"
    return Response({"title": title, **services.week(school, lessons)})


def today_for(profile):
    """A teacher's lessons today, for their home page."""
    school = profile.school
    day = school_localdate(school).isoweekday()
    lessons = Lesson.objects.filter(school=school, teacher=profile, day=day) \
        .select_related("school_class", "subject", "room", "period", "teacher")
    return [{**services.lesson_row(lesson), "start_time": lesson.period.start_time.strftime("%H:%M"),
             "end_time": lesson.period.end_time.strftime("%H:%M"), "period_name": lesson.period.name}
            for lesson in lessons]


def guardian_week(student):
    """A parent's view of their child's week."""
    return {"title": f"{student.first_name} {student.last_name}",
            **services.week(student.school, services.student_lessons(student))}


@api_view(["GET"])
@permission_classes([IsAuthenticated, AdminWritesStaffReads])
def unstaffed(request):
    """Lessons with no teacher, or a teacher whose account was deactivated, so an admin can cover them."""
    return Response(services.unstaffed(request.user.profile.school))

