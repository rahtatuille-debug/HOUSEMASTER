from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.permissions import HasSchoolProfile, IsSchoolAdmin

from .models import Guardian, GuardianInvite
from .permissions import IsGuardian
from .serializers import (
    AcceptGuardianInviteSerializer,
    GuardianInvitePreviewSerializer,
    GuardianInviteSerializer,
    GuardianNameSerializer,
    GuardianStudentSerializer,
    GuardianGradeSerializer,
    GuardianReportSerializer,
)


class GuardianInviteViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """Admin-only creation/management of guardian invites, scoped to the caller's school."""

    queryset = GuardianInvite.objects.all()
    serializer_class = GuardianInviteSerializer
    permission_classes = [HasSchoolProfile, IsSchoolAdmin]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def perform_create(self, serializer):
        for student in serializer.validated_data.get("students", []):
            self.check_belongs_to_school(student, "Student")
        serializer.save(school=self.get_school(), invited_by=self.request.user)


class GuardianStudentViewSet(viewsets.ReadOnlyModelViewSet):
    """A guardian's read-only view of the children linked to their account."""

    serializer_class = GuardianStudentSerializer
    permission_classes = [IsAuthenticated, IsGuardian]

    def get_queryset(self):
        return self.request.user.guardian.students.select_related("school_class__year_group").all()

    @action(detail=True, methods=["get"])
    def grades(self, request, pk=None):
        student = self.get_object()
        grades = student.grades.select_related("subject", "term").order_by("-recorded_at")
        if term_id := request.query_params.get("term"):
            grades = grades.filter(term_id=term_id)
        return Response(GuardianGradeSerializer(grades, many=True).data)

    @action(detail=True, methods=["get"])
    def reports(self, request, pk=None):
        student = self.get_object()
        # Draft/reviewed reports are internal staff work. Guardians only see
        # a report once the school has explicitly finalized it.
        reports = student.reports.filter(status="finalized").select_related("term").order_by("-generated_at")
        return Response(GuardianReportSerializer(reports, many=True).data)


class GuardianInvitePreviewView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            invite = GuardianInvite.objects.get(token=token)
        except GuardianInvite.DoesNotExist:
            return Response({"detail": "Invite not found."}, status=404)
        return Response(GuardianInvitePreviewSerializer(invite).data)


class AcceptGuardianInviteView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AcceptGuardianInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)}, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, IsGuardian])
def guardian_me(request):
    guardian = request.user.guardian
    if request.method == "PATCH":
        serializer = GuardianNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        guardian.display_name = serializer.validated_data["name"]
        guardian.save(update_fields=["display_name"])
    return Response({
        "name": guardian.name,
        "school": {"id": guardian.school_id, "name": guardian.school.name},
        "students": GuardianStudentSerializer(guardian.students.all(), many=True).data,
    })
