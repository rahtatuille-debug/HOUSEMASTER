from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.mixins import SchoolScopedViewSetMixin

from activity.services import log_activity

from .emails import send_admin_password_reset

from .models import Invite, Profile, TeachingAssignment
from .permissions import HasSchoolProfile, IsSchoolAdmin
from .serializers import (
    AcceptInviteSerializer,
    ConfirmPasswordResetSerializer,
    EmailTokenObtainPairSerializer,
    InvitePreviewSerializer,
    InviteSerializer,
    ProfileNameSerializer,
    RequestPasswordResetSerializer,
    StaffMemberSerializer,
    TeachingAssignmentSerializer,
)


class EmailTokenObtainPairView(TokenObtainPairView):
    """Login by email + password instead of username + password."""

    serializer_class = EmailTokenObtainPairSerializer


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def me(request):
    profile = request.user.profile
    if request.method == "PATCH":
        serializer = ProfileNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile.display_name = serializer.validated_data["name"]
        profile.save(update_fields=["display_name"])
    return Response(
        {
            "id": request.user.id,
            "name": profile.name,
            "role": profile.role,
            "school": {"id": profile.school.id, "name": profile.school.name},
            "assignments": TeachingAssignmentSerializer(
                profile.assignments.select_related("school_class", "subject"), many=True
            ).data,
        }
    )


class InviteViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Invite.objects.all()
    serializer_class = InviteSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile, IsSchoolAdmin]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def perform_create(self, serializer):
        invite = serializer.save(school=self.get_school(), invited_by=self.request.user)
        log_activity(
            school=invite.school, actor=self.request.user, action="staff_invite.created", target=invite,
            summary=f"Invited {invite.name} ({invite.email}) to join as {invite.get_role_display().lower()}",
            email=invite.email, role=invite.role,
        )

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        invite = self.get_object()
        if invite.is_accepted:
            raise ValidationError("This invite has already been accepted.")
        invite.renew()
        log_activity(
            school=invite.school, actor=request.user, action="staff_invite.renewed", target=invite,
            summary=f"Renewed the staff invite for {invite.name} ({invite.email}) with a new link",
        )
        return Response(self.get_serializer(invite).data)

    def perform_destroy(self, instance):
        log_activity(
            school=instance.school, actor=self.request.user, action="staff_invite.cancelled",
            target=instance, summary=f"Cancelled the staff invite for {instance.name} ({instance.email})",
            email=instance.email,
        )
        instance.delete()


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def dashboard(request):
    """Admin home page: today's attendance and everything waiting on an admin."""
    from .dashboard import build_dashboard

    return Response(build_dashboard(request.user.profile.school))


class StaffViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Admin-only list of the school's staff, with role changes (PATCH role)
    and deactivate/reactivate actions. Deactivating sets User.is_active to
    False, which blocks login and every API request straight away, but
    keeps the account and everything linked to it (the same soft approach
    as Student.is_active). The school must always keep at least one active
    admin, and admins can't deactivate or demote themselves.
    """

    queryset = Profile.objects.select_related("user").order_by("-user__is_active", "display_name")
    serializer_class = StaffMemberSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile, IsSchoolAdmin]
    http_method_names = ["get", "patch", "post", "head", "options"]
    filterset_fields = ["role"]

    def create(self, request, *args, **kwargs):
        # New staff join through invites, never by being created here.
        return Response({"detail": "Use an invite to add staff."}, status=405)

    def _other_active_admins(self, profile):
        return Profile.objects.filter(
            school=profile.school, role=Profile.Role.ADMIN, user__is_active=True
        ).exclude(pk=profile.pk)

    def _guard_admin_loss(self, profile, what):
        if profile.user_id == self.request.user.id:
            raise ValidationError(f"You can't {what} yourself. Ask another admin.")
        if profile.role == Profile.Role.ADMIN and not self._other_active_admins(profile).exists():
            raise ValidationError(f"You can't {what} the school's only admin.")

    def partial_update(self, request, *args, **kwargs):
        profile = self.get_object()
        role = request.data.get("role")
        if role not in Profile.Role.values:
            raise ValidationError({"role": "Role must be admin or teacher."})
        old = profile.role
        if role != old:
            if old == Profile.Role.ADMIN:
                self._guard_admin_loss(profile, "remove admin rights from")
            profile.role = role
            profile.save(update_fields=["role"])
            log_activity(
                school=profile.school, actor=request.user, action="staff.role_changed", target=profile,
                summary=f"Changed {profile.name}'s role from {old} to {role}", old=old, new=role,
            )
        return Response(self.get_serializer(profile).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        profile = self.get_object()
        if profile.user.is_active:
            self._guard_admin_loss(profile, "deactivate")
            profile.user.is_active = False
            profile.user.save(update_fields=["is_active"])
            log_activity(
                school=profile.school, actor=request.user, action="staff.deactivated", target=profile,
                summary=f"Deactivated {profile.name}'s account",
            )
        return Response(self.get_serializer(profile).data)

    @action(detail=True, methods=["post"], url_path="send-password-reset")
    def send_password_reset(self, request, pk=None):
        profile = self.get_object()
        if not profile.user.is_active:
            raise ValidationError("Reactivate this account before sending a password reset.")
        if not profile.user.email:
            raise ValidationError("This account has no email address to send a reset link to.")
        send_admin_password_reset(profile.user)
        log_activity(
            school=profile.school, actor=request.user, action="password.reset_sent", target=profile,
            summary=f"Sent {profile.name} a password reset email",
        )
        return Response({"detail": f"A password reset link was emailed to {profile.user.email}."})

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        profile = self.get_object()
        if not profile.user.is_active:
            profile.user.is_active = True
            profile.user.save(update_fields=["is_active"])
            log_activity(
                school=profile.school, actor=request.user, action="staff.reactivated", target=profile,
                summary=f"Reactivated {profile.name}'s account",
            )
        return Response(self.get_serializer(profile).data)


class TeachingAssignmentViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """Admin-only: which classes and subjects each teacher teaches. Filter with ?teacher=."""

    queryset = TeachingAssignment.objects.select_related("teacher", "school_class", "subject")
    serializer_class = TeachingAssignmentSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile, IsSchoolAdmin]
    http_method_names = ["get", "post", "delete", "head", "options"]
    filterset_fields = ["teacher", "school_class", "subject"]
    school_lookup = "teacher__school"

    @staticmethod
    def _describe(assignment):
        subject = assignment.subject.name if assignment.subject else "(all subjects)"
        return f"{assignment.teacher.name} to {assignment.school_class.name} {subject}"

    def perform_create(self, serializer):
        data = serializer.validated_data
        self.check_belongs_to_school(data["teacher"], "teacher")
        self.check_belongs_to_school(data["school_class"].year_group.school, "school_class")
        if data.get("subject") is not None:
            self.check_belongs_to_school(data["subject"], "subject")
        assignment = serializer.save()
        log_activity(
            school=self.get_school(), actor=self.request.user, action="assignment.created",
            target=assignment, summary=f"Assigned {self._describe(assignment)}",
        )

    def perform_destroy(self, instance):
        log_activity(
            school=self.get_school(), actor=self.request.user, action="assignment.deleted",
            target=instance, summary=f"Removed {self._describe(instance)}",
        )
        instance.delete()


class InvitePreviewView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            invite = Invite.objects.get(token=token)
        except Invite.DoesNotExist:
            return Response({"detail": "Invite not found."}, status=404)
        return Response(InvitePreviewSerializer(invite).data)


class AcceptInviteView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AcceptInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log_activity(
            school=user.profile.school, actor=user, action="staff_invite.accepted", target=user.profile,
            summary=f"{user.profile.name} accepted their invite and joined as "
            f"{user.profile.get_role_display().lower()}",
        )
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)}, status=201)


class RequestPasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RequestPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Always the same response, whether or not that email is on file —
        # this endpoint must not reveal that.
        return Response({"detail": "If that account exists, a reset link has been sent."})


class ConfirmPasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ConfirmPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password has been reset. You can now log in."})
