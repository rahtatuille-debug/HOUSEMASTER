from rest_framework import viewsets

from accounts.mixins import SchoolScopedViewSetMixin

from .models import School, SchoolClass, Student
from .serializers import SchoolSerializer, SchoolClassSerializer, StudentSerializer


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

    def perform_create(self, serializer):
        school_class = serializer.validated_data.get("school_class")
        if school_class is not None:
            self.check_belongs_to_school(school_class.year_group.school, "school_class")
        # Force the school to the caller's own school regardless of what
        # (if anything) was supplied in the request body.
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        school_class = serializer.validated_data.get("school_class")
        if school_class is not None:
            self.check_belongs_to_school(school_class.year_group.school, "school_class")
        serializer.save(school=self.get_school())
