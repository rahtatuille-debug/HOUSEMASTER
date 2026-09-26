from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.permissions import HasSchoolProfile, IsSchoolAdmin
from accounts.emails import send_admin_password_reset
from activity.services import log_activity, student_name

from .models import Guardian, GuardianInvite
from .permissions import IsGuardian
from .serializers import (
    AcceptGuardianInviteSerializer,
    GuardianInvitePreviewSerializer,
    GuardianInviteSerializer,
    GuardianNameSerializer,
    ParentSerializer,
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
        invite = serializer.save(school=self.get_school(), invited_by=self.request.user)
        children = ", ".join(student_name(s) for s in invite.students.all())
        log_activity(
            school=invite.school, actor=self.request.user, action="parent_invite.created", target=invite,
            summary=f"Invited parent {invite.name} ({invite.email}) for {children}",
            email=invite.email, students=[s.id for s in invite.students.all()],
        )

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        invite = self.get_object()
        if invite.is_accepted:
            raise ValidationError("This invite has already been accepted.")
        invite.renew()
        log_activity(
            school=invite.school, actor=request.user, action="parent_invite.renewed", target=invite,
            summary=f"Renewed the parent invite for {invite.name} ({invite.email}) with a new link",
        )
        return Response(self.get_serializer(invite).data)

    def perform_destroy(self, instance):
        log_activity(
            school=instance.school, actor=self.request.user, action="parent_invite.cancelled",
            target=instance, summary=f"Cancelled the parent invite for {instance.name} ({instance.email})",
            email=instance.email,
        )
        instance.delete()


class ParentViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Admin-only list of the school's parent accounts. Admins can change
    which children a parent is linked to (PATCH students) and deactivate or
    reactivate the account. Deactivating blocks login straight away but
    keeps the account, its links and its message history.
    """

    queryset = Guardian.objects.select_related("user").prefetch_related("students").order_by(
        "-user__is_active", "display_name"
    )
    serializer_class = ParentSerializer
    permission_classes = [HasSchoolProfile, IsSchoolAdmin]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        return Response({"detail": "Use a parent invite to add parents."}, status=405)

    def partial_update(self, request, *args, **kwargs):
        guardian = self.get_object()
        if "students" not in request.data:
            raise ValidationError({"students": "Send the full list of linked student IDs."})
        serializer = self.get_serializer(guardian, data={"students": request.data["students"]}, partial=True)
        serializer.is_valid(raise_exception=True)
        new_students = serializer.validated_data["students"]
        for student in new_students:
            self.check_belongs_to_school(student, "Student")

        before = set(guardian.students.all())
        after = set(new_students)
        guardian.students.set(new_students)
        added, removed = after - before, before - after
        if added or removed:
            parts = []
            if added:
                parts.append("linked " + ", ".join(sorted(student_name(s) for s in added)))
            if removed:
                parts.append("unlinked " + ", ".join(sorted(student_name(s) for s in removed)))
            log_activity(
                school=guardian.school, actor=request.user, action="parent.children_changed",
                target=guardian, summary=f"Changed {guardian.name}'s children: " + "; ".join(parts),
                added=[s.id for s in added], removed=[s.id for s in removed],
            )
        return Response(self.get_serializer(guardian).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def _set_active(self, request, active):
        guardian = self.get_object()
        if guardian.user.is_active != active:
            guardian.user.is_active = active
            guardian.user.save(update_fields=["is_active"])
            verb = "Reactivated" if active else "Deactivated"
            log_activity(
                school=guardian.school, actor=request.user,
                action="parent.reactivated" if active else "parent.deactivated",
                target=guardian, summary=f"{verb} parent {guardian.name}'s account",
            )
        return Response(self.get_serializer(guardian).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        return self._set_active(request, False)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        return self._set_active(request, True)

    @action(detail=True, methods=["post"], url_path="send-password-reset")
    def send_password_reset(self, request, pk=None):
        guardian = self.get_object()
        if not guardian.user.is_active:
            raise ValidationError("Reactivate this account before sending a password reset.")
        if not guardian.user.email:
            raise ValidationError("This account has no email address to send a reset link to.")
        send_admin_password_reset(guardian.user)
        log_activity(
            school=guardian.school, actor=request.user, action="password.reset_sent", target=guardian,
            summary=f"Sent parent {guardian.name} a password reset email",
        )
        return Response({"detail": f"A password reset link was emailed to {guardian.user.email}."})


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
    def profile(self, request, pk=None):
        """
        A parent's view of their own child: details, teachers, attendance and
        the child's own average each term. Class and year-group averages are
        left out (they're built from other children's grades), as are other
        parents' contact details and anything staff-only.
        """
        from students.profile import build_profile

        student = self.get_object()
        full = build_profile(student, request.user)
        return Response({
            "student": GuardianStudentSerializer(student).data,
            "age": full["age"],
            "teachers": full["teachers"],
            "subjects": full["subjects"],
            "attendance": full["attendance"],
            "performance": [{"term": p["term"], "student": p["student"]} for p in full["performance"]],
        })

    @action(detail=True, methods=["get"])
    def photo(self, request, pk=None):
        from django.http import HttpResponse

        student = self.get_object()
        if not student.photo:
            raise NotFound("No photo.")
        response = HttpResponse(bytes(student.photo), content_type="image/jpeg")
        response["Cache-Control"] = "private, max-age=300"
        return response

    @action(detail=True, methods=["get"])
    def reports(self, request, pk=None):
        student = self.get_object()
        # Draft and submitted reports are internal staff work. Guardians only see
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
        log_activity(
            school=user.guardian.school, actor=user, action="parent_invite.accepted", target=user.guardian,
            summary=f"Parent {user.guardian.name} accepted their invite",
        )
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
        "id": request.user.id,
        "name": guardian.name,
        "school": {"id": guardian.school_id, "name": guardian.school.name},
        "students": GuardianStudentSerializer(guardian.students.all(), many=True).data,
    })
