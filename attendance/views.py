from datetime import date as date_cls

from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.scoping import ATTENDANCE, check_can_see_student, limit_to_visible_students, scope_class_ids
from activity.services import log_activity, student_name
from gradebook.locks import check_date_open
from housemaster.pagination import LongListPagination

from .models import AttendanceRecord
from .serializers import AttendanceRecordSerializer


class AttendanceRecordViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    # Ordered by id so pages are stable (F-14).
    queryset = AttendanceRecord.objects.order_by("id")
    serializer_class = AttendanceRecordSerializer
    pagination_class = LongListPagination
    filterset_fields = ["student", "date", "status"]
    school_lookup = "student__school"

    def get_queryset(self):
        return limit_to_visible_students(super().get_queryset(), self.request.user, area=ATTENDANCE)

    def perform_create(self, serializer):
        self.check_belongs_to_school(serializer.validated_data["student"].school, "student")
        check_can_see_student(self.request.user, serializer.validated_data["student"], ATTENDANCE)
        check_date_open(self.get_school(), serializer.validated_data["date"])
        record = serializer.save()
        log_activity(
            school=self.get_school(), actor=self.request.user, action="attendance.created", target=record,
            summary=f"Marked {student_name(record.student)} {record.status} on {record.date}",
            status=record.status,
        )

    def perform_update(self, serializer):
        student = serializer.validated_data.get("student", serializer.instance.student)
        self.check_belongs_to_school(student.school, "student")
        check_can_see_student(self.request.user, student, ATTENDANCE)
        check_date_open(self.get_school(), serializer.instance.date)
        check_date_open(self.get_school(), serializer.validated_data.get("date", serializer.instance.date))
        old = serializer.instance.status
        record = serializer.save()
        if old != record.status:
            log_activity(
                school=self.get_school(), actor=self.request.user, action="attendance.updated",
                target=record,
                summary=f"Changed {student_name(record.student)}'s attendance on {record.date} "
                f"from {old} to {record.status}",
                old=old, new=record.status,
            )

    def perform_destroy(self, instance):
        check_date_open(self.get_school(), instance.date)
        log_activity(
            school=self.get_school(), actor=self.request.user, action="attendance.deleted",
            target=instance,
            summary=f"Deleted {student_name(instance.student)}'s attendance record for {instance.date}",
            status=instance.status,
        )
        instance.delete()

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """GET ?date=YYYY-MM-DD (default today): each class's register that day, for the classes this person can see
        (all for admins and leaders; their own, their year or class for other staff). Classes with no active students are left out."""
        from students.localtime import school_localdate
        from students.models import SchoolClass, Student

        school = self.get_school()
        raw = request.query_params.get("date")
        try:
            day = date_cls.fromisoformat(raw) if raw else school_localdate(school)
        except ValueError:
            raise ValidationError({"date": ["Use a date like 2026-10-07."]})
        classes = SchoolClass.objects.filter(year_group__school=school).select_related("year_group")
        scope = scope_class_ids(request.user, ATTENDANCE)
        if scope is not None:
            classes = classes.filter(id__in=scope)
        students = Student.objects.filter(school=school, is_active=True, school_class__in=classes)
        sizes = dict(students.values("school_class").annotate(n=Count("id")).values_list("school_class", "n"))
        marks = {row["student__school_class"]: row for row in AttendanceRecord.objects.filter(
            student__in=students, date=day).values("student__school_class").annotate(
            marked=Count("id"), present=Count("id", filter=Q(status="present")), late=Count("id", filter=Q(status="late")),
            absent=Count("id", filter=Q(status="absent")), excused=Count("id", filter=Q(status="excused")))}
        rows = []
        for c in classes.order_by("year_group__order", "year_group__name", "name"):
            if not sizes.get(c.id):
                continue
            m = marks.get(c.id, {})
            rows.append({"id": c.id, "name": c.name, "year_group": c.year_group.name, "students": sizes[c.id],
                         **{k: m.get(k, 0) for k in ("marked", "present", "late", "absent", "excused")}})
        totals = {k: sum(r[k] for r in rows) for k in ("students", "marked", "present", "late", "absent", "excused")}
        totals["not_taken"] = sum(1 for r in rows if r["marked"] == 0)
        return Response({"date": day.isoformat(), "classes": rows, "totals": totals})
