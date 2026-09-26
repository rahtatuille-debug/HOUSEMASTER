from rest_framework import viewsets

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.scoping import assigned_class_ids, check_can_use_class, is_admin
from activity.services import log_activity, student_name

from .models import School, YearGroup, SchoolClass, Student
from .serializers import SchoolSerializer, YearGroupSerializer, SchoolClassSerializer, StudentSerializer


class SchoolViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """
    A school can only ever see/edit its own record (e.g. updating
    report_tone). Schools are provisioned separately (Django admin), not
    created or deleted through this API.
    """
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    http_method_names = ["get", "put", "patch", "head", "options"]

    def get_queryset(self):
        # School IS the tenant here, not a related object one hop away, so
        # this doesn't use the mixin's generic school_lookup filtering.
        return School.objects.filter(id=self.get_school().id)


class YearGroupViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = YearGroup.objects.all()
    serializer_class = YearGroupSerializer
    school_lookup = "school"

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class SchoolClassViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = SchoolClass.objects.all()
    serializer_class = SchoolClassSerializer
    school_lookup = "year_group__school"

    def perform_create(self, serializer):
        self.check_belongs_to_school(serializer.validated_data["year_group"], "year_group")
        serializer.save()

    def perform_update(self, serializer):
        year_group = serializer.validated_data.get("year_group", serializer.instance.year_group)
        self.check_belongs_to_school(year_group, "year_group")
        serializer.save()


class StudentViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    filterset_fields = ["school", "school_class", "is_active"]
    school_lookup = "school"

    def get_queryset(self):
        # Teachers only see students in the classes they teach.
        queryset = super().get_queryset()
        if is_admin(self.request.user):
            return queryset
        return queryset.filter(school_class_id__in=assigned_class_ids(self.request.user))

    def perform_create(self, serializer):
        school_class = serializer.validated_data.get("school_class")
        if school_class is not None:
            self.check_belongs_to_school(school_class.year_group.school, "school_class")
        check_can_use_class(self.request.user, school_class)
        # Force the school to the caller's own school regardless of what
        # (if anything) was supplied in the request body.
        student = serializer.save(school=self.get_school())
        log_activity(
            school=student.school, actor=self.request.user, action="student.created", target=student,
            summary=f"Added student {student_name(student)}",
        )

    def perform_update(self, serializer):
        if "school_class" in serializer.validated_data:
            school_class = serializer.validated_data["school_class"]
            if school_class is not None:
                self.check_belongs_to_school(school_class.year_group.school, "school_class")
            if school_class != serializer.instance.school_class:
                check_can_use_class(self.request.user, school_class)
        was_active = serializer.instance.is_active
        student = serializer.save(school=self.get_school())
        if was_active != student.is_active:
            verb = "Reactivated" if student.is_active else "Deactivated"
            action = "student.reactivated" if student.is_active else "student.deactivated"
            summary = f"{verb} student {student_name(student)}"
        else:
            action, summary = "student.updated", f"Updated student {student_name(student)}'s details"
        log_activity(school=student.school, actor=self.request.user, action=action, target=student,
                     summary=summary)
