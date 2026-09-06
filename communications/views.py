from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile, IsSchoolAdmin

from students.models import SchoolClass, YearGroup

from .models import Announcement
from .serializers import AnnouncementSerializer, GenerateAnnouncementTextSerializer
from .services import generate_announcement_text


class AnnouncementViewSet(viewsets.ModelViewSet):
    """Draft, publish and archive one-way administrative announcements."""

    queryset = Announcement.objects.select_related(
        "school", "year_group", "school_class", "created_by"
    )
    serializer_class = AnnouncementSerializer
    filterset_fields = ["audience", "status", "year_group", "school_class"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action in {"list", "retrieve", "generate_text"}:
            return [HasSchoolProfile()]
        return [IsSchoolAdmin()]

    def get_queryset(self):
        school = self.request.user.profile.school
        queryset = super().get_queryset().filter(school=school)
        if self.request.user.profile.role == "admin":
            return queryset
        # Today, staff membership is the only recipient relationship in the
        # product. Parent and class-targeted announcements remain private to
        # admins until parent accounts/teaching assignments are added.
        return queryset.filter(
            status=Announcement.Status.PUBLISHED,
            audience=Announcement.Audience.ALL_STAFF,
        )

    def _validate_targets(self, serializer):
        school = self.request.user.profile.school
        year_group = serializer.validated_data.get("year_group")
        school_class = serializer.validated_data.get("school_class")
        if year_group and year_group.school_id != school.id:
            raise PermissionDenied("year_group does not belong to your school.")
        if school_class and school_class.year_group.school_id != school.id:
            raise PermissionDenied("school_class does not belong to your school.")

    def perform_create(self, serializer):
        self._validate_targets(serializer)
        serializer.save(school=self.request.user.profile.school, created_by=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.status != Announcement.Status.DRAFT:
            raise ValidationError("Only draft announcements can be edited.")
        self._validate_targets(serializer)
        serializer.save()

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        announcement = self.get_object()
        if announcement.status != Announcement.Status.DRAFT:
            raise ValidationError("Only draft announcements can be published.")
        announcement.publish()
        return Response(self.get_serializer(announcement).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        announcement = self.get_object()
        if announcement.status != Announcement.Status.PUBLISHED:
            raise ValidationError("Only published announcements can be archived.")
        announcement.archive()
        return Response(self.get_serializer(announcement).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="generate-text")
    def generate_text(self, request):
        """Generate editable announcement wording from a staff member's brief.

        This action is deliberately available to both teachers and admins.
        It returns text only; it neither saves nor publishes an announcement.
        """
        input_serializer = GenerateAnnouncementTextSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        school = request.user.profile.school
        target_label = None

        if data.get("year_group"):
            try:
                target_label = YearGroup.objects.get(pk=data["year_group"], school=school).name
            except YearGroup.DoesNotExist:
                return Response({"detail": "Year group not found."}, status=status.HTTP_404_NOT_FOUND)
        if data.get("school_class"):
            try:
                school_class = SchoolClass.objects.select_related("year_group").get(
                    pk=data["school_class"], year_group__school=school
                )
                target_label = f"{school_class.year_group.name} — {school_class.name}"
            except SchoolClass.DoesNotExist:
                return Response({"detail": "School class not found."}, status=status.HTTP_404_NOT_FOUND)

        audience_label = Announcement.Audience(data["audience"]).label
        try:
            title, body = generate_announcement_text(
                school=school,
                summary=data["summary"],
                audience_label=audience_label,
                target_label=target_label,
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response({"title": title, "body": body}, status=status.HTTP_200_OK)
