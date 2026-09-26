from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from accounts.mixins import SchoolScopedViewSetMixin
from approvals.mixins import ApprovalRequiredMixin
from accounts.scoping import assigned_class_ids, check_can_use_class, is_admin
from activity.services import log_activity, student_name

from .models import School, YearGroup, SchoolClass, Student
from .photos import process_photo
from .profile import build_profile
from .serializers import SchoolSerializer, YearGroupSerializer, SchoolClassSerializer, StudentSerializer


class SchoolViewSet(ApprovalRequiredMixin, SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """
    A school can only ever see/edit its own record (e.g. updating
    report_tone). Schools are provisioned separately (Django admin), not
    created or deleted through this API.
    """
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    http_method_names = ["get", "put", "patch", "head", "options"]
    approval_kind = "school"
    approval_label = "school settings"
    approval_operations = {"update"}

    def get_queryset(self):
        # School IS the tenant here, not a related object one hop away, so
        # this doesn't use the mixin's generic school_lookup filtering.
        return School.objects.filter(id=self.get_school().id)


class YearGroupViewSet(ApprovalRequiredMixin, SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = YearGroup.objects.all()
    serializer_class = YearGroupSerializer
    school_lookup = "school"
    approval_kind = "year_group"
    approval_label = "year group"

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class SchoolClassViewSet(ApprovalRequiredMixin, SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = SchoolClass.objects.all()
    serializer_class = SchoolClassSerializer
    school_lookup = "year_group__school"
    approval_kind = "school_class"
    approval_label = "class"

    def check_change_request(self, serializer):
        if "year_group" in serializer.validated_data:
            self.check_belongs_to_school(serializer.validated_data["year_group"], "year_group")

    def perform_create(self, serializer):
        self.check_belongs_to_school(serializer.validated_data["year_group"], "year_group")
        serializer.save()

    def perform_update(self, serializer):
        year_group = serializer.validated_data.get("year_group", serializer.instance.year_group)
        self.check_belongs_to_school(year_group, "year_group")
        serializer.save()


class StudentViewSet(ApprovalRequiredMixin, SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Permanently deleting a student also deletes their grades, attendance
    and reports, so a teacher's delete needs an admin's approval.
    Deactivating (is_active=False) is the everyday way to remove a student.
    """

    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    filterset_fields = ["school", "school_class", "is_active"]
    school_lookup = "school"
    approval_kind = "student"
    approval_label = "student"
    approval_operations = {"delete"}

    def describe(self, obj):
        return student_name(obj)

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

    @action(detail=True, methods=["get"])
    def profile(self, request, pk=None):
        """Everything the student profile page shows. Same visibility as the student itself."""
        student = self.get_object()
        return Response({"student": self.get_serializer(student).data, **build_profile(student, request.user)})

    @action(detail=True, methods=["get", "post", "delete"], parser_classes=[MultiPartParser])
    def photo(self, request, pk=None):
        """
        GET returns the photo as a JPEG (404 if there isn't one). POST a
        multipart `photo` file to set it; DELETE removes it. Anyone who can
        edit the student can change the photo.
        """
        student = self.get_object()
        if request.method == "GET":
            if not student.photo:
                raise NotFound("This student has no photo.")
            response = HttpResponse(bytes(student.photo), content_type="image/jpeg")
            response["Cache-Control"] = "private, max-age=300"
            return response
        if request.method == "POST":
            upload = request.FILES.get("photo")
            if upload is None:
                from rest_framework.exceptions import ValidationError

                raise ValidationError({"photo": "Choose a photo to upload."})
            student.photo = process_photo(upload)
            student.photo_updated_at = timezone.now()
            verb = "Changed"
        else:
            student.photo = None
            student.photo_updated_at = None
            verb = "Removed"
        student.save(update_fields=["photo", "photo_updated_at"])
        log_activity(
            school=student.school, actor=request.user, action="student.photo_changed", target=student,
            summary=f"{verb} {student_name(student)}'s photo",
        )
        return Response(self.get_serializer(student).data)

