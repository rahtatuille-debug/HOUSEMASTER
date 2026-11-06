"""One login, several schools (accounts/memberships.py): which ones, and switching between them."""
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from activity.services import log_activity

from .memberships import all_memberships, describe, find
from .tokens import tokens_for


def _current(user):
    return getattr(user, "profile", None) or getattr(user, "guardian", None)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def memberships(request):
    """Every school (and role) this login can use, marking the one this session is in."""
    current = _current(request.user)
    return Response([describe(m, current) for m in all_memberships(request.user)])


class SwitchThrottle(UserRateThrottle):
    rate = "60/hour"


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([SwitchThrottle])
def switch(request):
    """POST {membership: "staff:12"}: new tokens for that school. The old ones still work until they expire."""
    membership = find(request.user, str(request.data.get("membership") or ""))
    if membership is None:
        raise serializers.ValidationError({"membership": "That isn't one of your schools."})
    log_activity(school=membership.school, actor=request.user, action="account.switched", target=membership,
                 summary=f"{membership.name} switched to {membership.school.name}")
    return Response({**tokens_for(request.user, membership), "membership": describe(membership, membership)})
