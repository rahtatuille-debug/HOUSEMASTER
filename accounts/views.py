from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .permissions import HasSchoolProfile


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
