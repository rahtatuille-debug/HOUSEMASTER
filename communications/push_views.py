"""Turn phone and browser notifications on or off for one device (communications/push.py)."""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.conf import settings

from activity.services import log_activity

from . import push
from .models import PushSubscription


def _school(user):
    profile = getattr(user, "profile", None)
    guardian = getattr(user, "guardian", None)
    return getattr(profile, "school", None) or getattr(guardian, "school", None)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def push_settings(request):
    """Whether the school's server can send notifications, the key the browser needs, and whether
    this device (?endpoint=) or any of the user's devices is turned on."""
    subs = PushSubscription.objects.filter(user=request.user)
    if request.query_params.get("endpoint"):
        subs = subs.filter(endpoint=request.query_params["endpoint"])
    on = push.enabled()
    return Response({"enabled": on, "public_key": settings.VAPID_PUBLIC_KEY if on else "", "subscribed": subs.exists()})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def push_subscribe(request):
    endpoint = str(request.data.get("endpoint") or "")
    keys = request.data.get("keys") if isinstance(request.data.get("keys"), dict) else {}
    if not push.allowed_endpoint(endpoint) or len(endpoint) > 1000:
        raise ValidationError({"endpoint": ["This browser's notification service isn't supported."]})
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    if len(p256dh) > 200 or len(auth) > 100 or not push.valid_keys(p256dh, auth):
        raise ValidationError({"keys": ["These notification keys aren't valid."]})
    # A device belongs to whoever last signed in on it.
    PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={"user": request.user, "p256dh": p256dh,
                                                                           "auth": auth})
    school = _school(request.user)
    if school is not None:
        log_activity(school=school, actor=request.user, action="push.subscribed",
                     summary="Turned on phone or browser notifications on a device")
    return Response({"subscribed": True}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def push_unsubscribe(request):
    deleted, _ = PushSubscription.objects.filter(user=request.user, endpoint=str(request.data.get("endpoint") or "")).delete()
    school = _school(request.user)
    if deleted and school is not None:
        log_activity(school=school, actor=request.user, action="push.unsubscribed",
                     summary="Turned off phone or browser notifications on a device")
    return Response(status=status.HTTP_204_NO_CONTENT)
