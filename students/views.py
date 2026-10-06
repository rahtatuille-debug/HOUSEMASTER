from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from accounts.mixins import SchoolScopedViewSetMixin
from approvals.mixins import ApprovalRequiredMixin
from accounts.scoping import assigned_class_ids, check_can_use_class, is_admin
from activity.services import log_activity, student_name

from .models import School, YearGroup, SchoolClass, Student
from accounts.permissions import HasSchoolProfile, IsSchoolAdmin

from housemaster.pagination import PagedOnRequest

from .photos import process_photo
from boarding.services import release_boarders

from .promotion import apply_promotion, plan_promotion, summarize
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

    def check_change_request(self, serializer):
        # The time zone decides what "today" is for every register, so only
        # an admin sets it; a teacher can't even ask for it (B-4).
        if "timezone" in serializer.validated_data and not is_admin(self.request.user):
            raise PermissionDenied("Only an admin can change the school's time zone.")


class YearGroupViewSet(ApprovalRequiredMixin, SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = YearGroup.objects.order_by("order", "name")
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

    queryset = Student.objects.select_related("school", "school_class__year_group").prefetch_related("subject_choices")
    serializer_class = StudentSerializer
    filterset_fields = ["school", "school_class", "is_active"]
    # Pages only when asked (?page= / ?page_size=); the whole list otherwise, as before (E-1).
    pagination_class = PagedOnRequest
    school_lookup = "school"
    approval_kind = "student"
    approval_label = "student"
    approval_operations = {"delete"}

    def describe(self, obj):
        return student_name(obj)

    def get_queryset(self):
        # Teachers only see students in the classes they teach.
        from django.db.models import Exists, OuterRef

        from support.models import SupportConcern

        from django.db.models import Q

        queryset = super().get_queryset().annotate(needs_support=Exists(SupportConcern.objects.filter(
            student=OuterRef("pk"), status=SupportConcern.Status.OPEN)))
        params = self.request.query_params
        # Search and filters on the server, so a paged list finds students on any page (E-1).
        for word in (params.get("q") or "").split():
            queryset = queryset.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word)
                                       | Q(external_id__icontains=word))
        if params.get("needs_support") in ("1", "true"):
            queryset = queryset.filter(needs_support=True)
        # A stable order, so pages never repeat or skip a student.
        queryset = queryset.order_by("last_name", "first_name", "id")
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
        was_boarding = serializer.instance.mode_of_learning == "boarding"
        student = serializer.save(school=self.get_school())
        # Leaving, deactivation and going back to day all give up the bed (boarding.services.release_boarders).
        if was_active and not student.is_active:
            release_boarders([student.id], "left_school", self.request.user)
        elif was_boarding and student.mode_of_learning != "boarding":
            release_boarders([student.id], "no_longer_boarding", self.request.user)
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

    @action(detail=True, methods=["get"], url_path="term-summary")
    def term_summary(self, request, pk=None):
        """This student's results for a term, the way their school's system reports them."""
        from gradebook.models import Term
        from gradebook.systems import term_summary

        student = self.get_object()
        try:
            term = Term.objects.get(pk=request.query_params.get("term"), school=student.school)
        except (Term.DoesNotExist, ValueError, TypeError):
            raise NotFound("Term not found.")
        report = student.reports.filter(term=term, status="finalized").select_related("school_class").first()
        return Response(term_summary(student, term, report))

    # Data protection requests (Kenya Data Protection Act). Admins only.
    @action(detail=True, methods=["get"], url_path="data-export", permission_classes=[HasSchoolProfile, IsSchoolAdmin])
    def data_export(self, request, pk=None):
        """Everything held about this student and their parents, as an Excel workbook (or JSON with ?format=json)."""
        from django.utils.text import slugify

        from .privacy import family_export

        student = self.get_object()
        log_activity(
            school=student.school, actor=request.user, action="student.data_exported", target=student,
            summary=f"Exported all personal data held about {student_name(student)} and their parents",
        )
        if request.query_params.get("format") == "json":
            from .privacy import family_export_data

            return Response(family_export_data(student))
        response = HttpResponse(
            family_export(student),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        name = slugify(student_name(student)) or "student"
        response["Content-Disposition"] = f'attachment; filename="personal-data-{name}.xlsx"'
        return response

    @action(detail=True, methods=["post"], url_path="remove-personal-data",
            permission_classes=[HasSchoolProfile, IsSchoolAdmin])
    def remove_personal_data(self, request, pk=None):
        """
        Remove a family's personal details on request. The admin must type
        the student's full name to confirm; this can't be undone.
        """
        from .privacy import remove_personal_data

        student = self.get_object()
        typed = " ".join(str(request.data.get("confirm_name", "")).split()).lower()
        if typed != " ".join(student_name(student).split()).lower():
            raise ValidationError({"confirm_name": "Type the student's full name exactly to confirm."})
        counts = remove_personal_data(student, request.user)
        return Response({"removed": True, **counts})


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def promote_students(request):
    """
    End of year (admins). Body: {"moves": [{"from_class": id, "to_class": id or null}],
    "commit": true/false}. Without commit it's a preview of how many students each
    move affects; with commit it moves everyone in one step.
    """
    school = request.user.profile.school
    plan = plan_promotion(school, request.data.get("moves") or [])
    if not plan:
        from rest_framework.exceptions import ValidationError

        raise ValidationError("Choose where at least one class moves to.")
    commit = request.data.get("commit") is True
    if commit:
        apply_promotion(school, request.user, plan)
    return Response({"committed": commit, "moves": summarize(plan)})

