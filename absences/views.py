from datetime import date as date_cls

from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.permissions import HasSchoolProfile
from accounts.scoping import ATTENDANCE, is_admin, limit_to_visible_students
from activity.services import display_name, log_activity, student_name

from . import services
from .models import AbsenceReport, AbsenceSettings


class AbsenceReportSerializer(serializers.ModelSerializer):
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)
    student_name = serializers.SerializerMethodField()
    class_name = serializers.CharField(source="student.school_class.name", default="", read_only=True)

    class Meta:
        model = AbsenceReport
        fields = ["id", "student", "student_name", "class_name", "start_date", "end_date", "reason", "reason_label",
                  "details", "reported_by_name", "created_at", "cancelled_at", "seen_by_name", "seen_at"]
        read_only_fields = ["student", "reported_by_name", "created_at", "cancelled_at", "seen_by_name", "seen_at"]

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}"


# Parents (called from guardians.views.GuardianStudentViewSet) -----------------

def guardian_list(student):
    reports = AbsenceReport.objects.filter(student=student).select_related("student__school_class")[:30]
    return AbsenceReportSerializer(reports, many=True).data


def guardian_report(request, student):
    """A parent tells the school their child is or will be away."""
    serializer = AbsenceReportSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    problem = services.date_problem(student.school, data["start_date"], data["end_date"])
    if problem:
        raise ValidationError(problem)
    if AbsenceReport.objects.filter(student=student, cancelled_at__isnull=True, start_date__lte=data["end_date"],
                                    end_date__gte=data["start_date"]).exists():
        raise ValidationError({"start_date": ["You've already told the school about an absence on these days. "
                                              "Cancel that one first to change it."]})
    report = serializer.save(school=student.school, student=student, reported_by=request.user,
                             reported_by_name=request.user.guardian.name)
    services.tell_class_teachers(report)
    # Never the details: they can be about the child's health.
    log_activity(school=student.school, actor=request.user, action="absence.reported", target=student,
                 summary=f"A parent reported an absence for {student_name(student)} "
                         f"({report.start_date} to {report.end_date}, {report.get_reason_display().lower()})")
    return AbsenceReportSerializer(report).data


def guardian_cancel(request, student, report_id):
    report = AbsenceReport.objects.filter(pk=report_id, student=student, cancelled_at__isnull=True).first()
    if report is None:
        raise NotFound("No absence to cancel.")
    report.cancelled_at = timezone.now()
    report.save(update_fields=["cancelled_at"])
    log_activity(school=student.school, actor=request.user, action="absence.cancelled", target=student,
                 summary=f"A parent cancelled the absence they reported for {student_name(student)}")
    return AbsenceReportSerializer(report).data


# Staff ---------------------------------------------------------------------------

class AbsenceReportViewSet(SchoolScopedViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    What parents have reported, for staff who can see the children's attendance.
    GET ?date=YYYY-MM-DD (covering that day), ?school_class=, ?unseen=1, ?from=YYYY-MM-DD (ending on or after).
    POST /<id>/seen/ marks it read.
    """

    queryset = AbsenceReport.objects.select_related("student__school_class").order_by("start_date", "id")
    serializer_class = AbsenceReportSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile]
    school_lookup = "school"
    pagination_class = None

    def get_queryset(self):
        qs = limit_to_visible_students(super().get_queryset(), self.request.user, area=ATTENDANCE)
        params = self.request.query_params
        try:
            if day := params.get("date"):
                d = date_cls.fromisoformat(day)
                qs = qs.filter(start_date__lte=d, end_date__gte=d, cancelled_at__isnull=True)
            if since := params.get("from"):
                qs = qs.filter(end_date__gte=date_cls.fromisoformat(since))
        except ValueError:
            raise ValidationError({"date": ["Use a date like 2026-10-07."]})
        if school_class := params.get("school_class"):
            qs = qs.filter(student__school_class_id=school_class)
        if params.get("unseen"):
            qs = qs.filter(seen_at__isnull=True, cancelled_at__isnull=True)
        return qs[:500]

    @action(detail=True, methods=["post"])
    def seen(self, request, pk=None):
        report = limit_to_visible_students(AbsenceReport.objects.filter(school=self.get_school()), request.user,
                                           area=ATTENDANCE).filter(pk=pk).first()
        if report is None:
            raise NotFound("Not found.")
        if report.seen_at is None:
            report.seen_at = timezone.now()
            report.seen_by_name = display_name(request.user)
            report.save(update_fields=["seen_at", "seen_by_name"])
        return Response(AbsenceReportSerializer(report).data)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def absence_settings(request):
    """GET (any staff) / PATCH {alerts_enabled} (admins): whether parents get same-day absence alerts."""
    school = request.user.profile.school
    if request.method == "PATCH":
        if not is_admin(request.user):
            raise PermissionDenied("Only admins can change this.")
        value = request.data.get("alerts_enabled")
        if not isinstance(value, bool):
            raise ValidationError({"alerts_enabled": ["true or false."]})
        AbsenceSettings.objects.update_or_create(school=school, defaults={"alerts_enabled": value})
        log_activity(school=school, actor=request.user, action="absence.settings",
                     summary=f"Turned absence alerts to parents {'on' if value else 'off'}")
    return Response({"alerts_enabled": services.alerts_enabled(school)})
