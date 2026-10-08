from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.mixins import SchoolScopedViewSetMixin

from activity.services import log_activity
from gradebook.levels import school_summary

from .emails import send_admin_password_reset, send_staff_invite_email

from .models import Invite, Profile, StaffRole, TeachingAssignment
from .permissions import HasSchoolProfile, IsLeader, IsSchoolAdmin
from .scoping import permissions_for
from .throttles import (
    InviteIPThrottle,
    InviteSendRecipientThrottle,
    InviteSendUserThrottle,
    LoginEmailThrottle,
    LoginIPThrottle,
    PasswordResetConfirmIPThrottle,
    PasswordResetEmailThrottle,
    PasswordResetIPThrottle,
    TokenRefreshIPThrottle,
)
from .tokens import tokens_for
from .serializers import (
    AcceptInviteSerializer,
    ConfirmPasswordResetSerializer,
    EmailTokenObtainPairSerializer,
    InvitePreviewSerializer,
    InviteSerializer,
    ProfileNameSerializer,
    RequestPasswordResetSerializer,
    StaffMemberSerializer,
    StaffRoleSerializer,
    TeachingAssignmentSerializer,
)


class EmailTokenObtainPairView(TokenObtainPairView):
    """Login by email + password instead of username + password."""

    serializer_class = EmailTokenObtainPairSerializer
    # Only failed attempts count towards these (accounts/throttles.py).
    throttle_classes = [LoginIPThrottle, LoginEmailThrottle]

    def get_throttles(self):
        # Keep the same instances so a failed login can be recorded below.
        if not hasattr(self, "_throttle_instances"):
            self._throttle_instances = super().get_throttles()
        return self._throttle_instances

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except AuthenticationFailed:
            for throttle in self.get_throttles():
                throttle.record_failure()
            raise


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [TokenRefreshIPThrottle]


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def me(request):
    from boarding.services import is_boarding_staff

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
            "tour_seen": profile.tour_seen_at is not None,
            "is_boarding_staff": is_boarding_staff(request.user),
            "school": school_summary(profile.school),
            "assignments": TeachingAssignmentSerializer(
                profile.assignments.select_related("school_class", "subject"), many=True
            ).data,
            # Extra responsibilities, and what the app should offer because of them.
            "roles": [{"role": r.role, "role_label": r.get_role_display(), "scope_name": r.scope_name,
                       "year_group": r.year_group_id, "subject": r.subject_id, "school_class": r.school_class_id}
                      for r in profile.staff_roles.select_related("year_group", "subject", "school_class")],
            "permissions": permissions_for(request.user),
        }
    )


class InviteViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Invite.objects.all()
    serializer_class = InviteSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile, IsSchoolAdmin]
    throttle_classes = [InviteSendUserThrottle, InviteSendRecipientThrottle]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def perform_create(self, serializer):
        invite = serializer.save(school=self.get_school(), invited_by=self.request.user)
        log_activity(
            school=invite.school, actor=self.request.user, action="staff_invite.created", target=invite,
            summary=f"Invited {invite.name} ({invite.email}) to join as {invite.get_role_display().lower()}",
            email=invite.email, role=invite.role,
        )
        send_staff_invite_email(invite, self.request.user.profile.name)

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
        send_staff_invite_email(invite, request.user.profile.name)
        return Response(self.get_serializer(invite).data)

    def perform_destroy(self, instance):
        log_activity(
            school=instance.school, actor=self.request.user, action="staff_invite.cancelled",
            target=instance, summary=f"Cancelled the staff invite for {instance.name} ({instance.email})",
            email=instance.email,
        )
        instance.delete()


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsLeader])
def dashboard(request):
    """The school's home page (admins and leadership): today's attendance and everything waiting."""
    from .dashboard import build_dashboard

    return Response(build_dashboard(request.user.profile.school))


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def governor_summary(request):
    """
    School-wide figures for governors (and leaders): numbers only, never a
    named student or parent.
    """
    from .dashboard import governor_figures
    from .scoping import is_governor, is_leader

    if not (is_governor(request.user) or is_leader(request.user)):
        raise PermissionDenied("Only governors and school leaders can see this.")
    return Response(governor_figures(request.user.profile.school))


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
            raise ValidationError({"role": "Role must be admin, teacher or governor."})
        old = profile.role
        if role != old:
            if old == Profile.Role.ADMIN:
                self._guard_admin_loss(profile, "remove admin rights from")
            if role == Profile.Role.GOVERNOR and (profile.assignments.exists() or profile.staff_roles.exists()):
                raise ValidationError({"role": "Remove their classes and roles first: governor accounts are read-only."})
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
        # Their lessons stay on the timetable with their name (history), and now show as unstaffed (F).
        from timetable.models import Lesson
        from timetable.services import unstaffed_row

        lessons = Lesson.objects.filter(teacher=profile).select_related("school_class", "subject", "teacher__user",
                                                                        "room", "period")
        return Response({**self.get_serializer(profile).data, "lessons": [unstaffed_row(x) for x in lessons]})

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


class StaffRoleViewSet(viewsets.ModelViewSet):
    """
    Admin-only: staff members' extra roles (Head of Year, Nurse, ...). POST
    {profile, role, year_group|subject|school_class as the role needs};
    DELETE removes one. Filter with ?profile=.
    """

    serializer_class = StaffRoleSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile, IsSchoolAdmin]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = StaffRole.objects.filter(profile__school=self.request.user.profile.school).select_related(
            "profile__user", "year_group", "subject", "school_class")
        if self.request.query_params.get("profile"):
            queryset = queryset.filter(profile=self.request.query_params["profile"])
        return queryset

    @staticmethod
    def _describe(role):
        return f"{role.get_role_display()}{f' for {role.scope_name}' if role.scope_name else ''}"

    def perform_create(self, serializer):
        from activity.services import display_name

        role = serializer.save(assigned_by_name=display_name(self.request.user))
        log_activity(school=role.profile.school, actor=self.request.user, action="staff.role_added",
                     target=role.profile, summary=f"Made {role.profile.name} {self._describe(role)}")

    def perform_destroy(self, instance):
        log_activity(school=instance.profile.school, actor=self.request.user, action="staff.role_removed",
                     target=instance.profile, summary=f"Removed {self._describe(instance)} from {instance.profile.name}")
        instance.delete()


class InvitePreviewView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [InviteIPThrottle]

    def get(self, request, token):
        try:
            invite = Invite.objects.get(token=token)
        except Invite.DoesNotExist:
            return Response({"detail": "Invite not found."}, status=404)
        return Response(InvitePreviewSerializer(invite).data)


class AcceptInviteView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [InviteIPThrottle]

    def post(self, request):
        serializer = AcceptInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log_activity(
            school=user.profile.school, actor=user, action="staff_invite.accepted", target=user.profile,
            summary=f"{user.profile.name} accepted their invite and joined as "
            f"{user.profile.get_role_display().lower()}",
        )
        return Response(tokens_for(user), status=201)


class RequestPasswordResetView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetIPThrottle, PasswordResetEmailThrottle]

    def post(self, request):
        serializer = RequestPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Always the same response, whether or not that email is on file —
        # this endpoint must not reveal that.
        return Response({"detail": "If that account exists, a reset link has been sent."})


class ConfirmPasswordResetView(APIView):
    permission_classes = [AllowAny]
    # Its own per-IP bucket, not shared with invites and sign-up links.
    throttle_classes = [PasswordResetConfirmIPThrottle]

    def post(self, request):
        serializer = ConfirmPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password has been reset. You can now log in."})


class LogoutView(APIView):
    """
    Signs out one session by retiring its refresh token. Needs no access
    token (it may already have expired) and always answers the same way,
    whether or not the token was valid, so it can be retried safely.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [TokenRefreshIPThrottle]

    def post(self, request):
        token = request.data.get("refresh")
        if not isinstance(token, str) or not token:
            raise ValidationError({"refresh": "This field is required."})
        try:
            RefreshToken(token).blacklist()
        except TokenError:
            pass
        return Response({"detail": "Signed out."})
