from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.mixins import SchoolScopedViewSetMixin

from .models import Invite
from .permissions import HasSchoolProfile, IsSchoolAdmin
from .serializers import (
    AcceptInviteSerializer,
    ConfirmPasswordResetSerializer,
    InvitePreviewSerializer,
    InviteSerializer,
    RequestPasswordResetSerializer,
)


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def me(request):
    profile = request.user.profile
    return Response(
        {
            "username": request.user.username,
            "role": profile.role,
            "school": {"id": profile.school.id, "name": profile.school.name},
        }
    )


class InviteViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Invite.objects.all()
    serializer_class = InviteSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile, IsSchoolAdmin]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(school=self.get_school(), invited_by=self.request.user)


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
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)}, status=201)


class RequestPasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RequestPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Always the same response, whether or not the username exists or
        # has an email on file — this endpoint must not reveal that.
        return Response({"detail": "If that account exists, a reset link has been sent."})


class ConfirmPasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ConfirmPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password has been reset. You can now log in."})