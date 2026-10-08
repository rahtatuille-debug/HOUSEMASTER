from datetime import date, timedelta

from django.db import transaction
from django.http import Http404, HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from activity.services import display_name, log_activity
from students.localtime import school_localdate
from students.models import YearGroup

from . import services
from .models import CalendarFeed, Event

FIELDS = ("title", "kind", "description", "location", "start_date", "end_date", "start_time", "end_time", "staff_only")


def _day(value, field):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError({field: ["Use a date like 2026-10-08."]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def calendar(request):
    """
    GET ?from=&to= (dates; default this month): the signed-in person's
    calendar. Staff see every event; parents see the events for their
    children's year groups, term dates and their children's club fixtures.
    """
    school, students = services.viewer(request.user)
    if school is None:
        raise PermissionDenied("This account has no school calendar.")
    today = school_localdate(school)
    start = _day(request.query_params["from"], "from") if request.query_params.get("from") else today.replace(day=1)
    end = _day(request.query_params["to"], "to") if request.query_params.get("to") else start + timedelta(days=41)
    if end < start or (end - start).days > services.MAX_DAYS:
        raise ValidationError({"to": [f"Choose up to {services.MAX_DAYS} days, ending after the start."]})
    manage = students is None and services.can_manage(request.user)
    body = {"from": start, "to": end, "today": today, "items": services.items(request.user, start, end), "can_manage": manage}
    if manage:
        body["year_groups"] = [{"id": y.id, "name": y.name} for y in YearGroup.objects.filter(school=school).order_by("order", "name")]
    return Response(body)


class EventSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Event
        fields = ["id", "title", "kind", "kind_label", "description", "location", "start_date", "end_date",
                  "start_time", "end_time", "staff_only", "created_by_name"]
        read_only_fields = ["created_by_name"]
        extra_kwargs = {"description": {"max_length": 2000}}

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Give the event a title.")
        return value.strip()

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        if get("end_date") and get("end_date") < get("start_date"):
            raise serializers.ValidationError({"end_date": ["The end date can't be before the start date."]})
        if get("end_time") and not get("start_time"):
            raise serializers.ValidationError({"start_time": ["Give a start time too, or leave both blank for all day."]})
        if get("end_time") and get("start_time") and get("end_time") <= get("start_time") \
                and (get("end_date") or get("start_date")) == get("start_date"):
            raise serializers.ValidationError({"end_time": ["The end time must be after the start time."]})
        return attrs


class EventViewSet(viewsets.ModelViewSet):
    """
    Calendar events (staff). Leadership, admins and the secretary add,
    change and remove them: {title, kind, description, location,
    start_date, end_date, start_time, end_time, staff_only, year_groups:
    [ids] (blank for the whole school)}.
    """

    serializer_class = EventSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Event.objects.filter(school=self.request.user.profile.school).prefetch_related("year_groups")

    def _check(self):
        if not services.can_manage(self.request.user):
            raise PermissionDenied("Only leadership, an admin or the secretary can change the calendar.")

    def _set_years(self, event, ids):
        if not isinstance(ids, list):
            raise ValidationError({"year_groups": ["Send a list."]})
        try:
            ids = {int(i) for i in ids}
        except (TypeError, ValueError):
            raise ValidationError({"year_groups": ["Year group not found."]})
        years = list(YearGroup.objects.filter(school=event.school, pk__in=ids))
        if len(years) != len(ids):
            raise ValidationError({"year_groups": ["Year group not found."]})
        event.year_groups.set(years)

    def _row(self, event):
        return services._event_row(Event.objects.prefetch_related("year_groups").get(pk=event.pk), True)

    def create(self, request, *args, **kwargs):
        self._check()
        serializer = self.get_serializer(data={k: v for k, v in request.data.items() if k in FIELDS})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            event = serializer.save(school=request.user.profile.school, created_by=request.user,
                                    created_by_name=display_name(request.user))
            self._set_years(event, request.data.get("year_groups") or [])
        log_activity(school=event.school, actor=request.user, action="calendar.event_added", target=event,
                     summary=f"Added {event.title} ({event.start_date.isoformat()}) to the calendar")
        return Response(self._row(event), status=201)

    def partial_update(self, request, *args, **kwargs):
        self._check()
        event = self.get_object()
        serializer = self.get_serializer(event, data={k: v for k, v in request.data.items() if k in FIELDS}, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            event = serializer.save()
            if "year_groups" in request.data:
                self._set_years(event, request.data["year_groups"] or [])
        log_activity(school=event.school, actor=request.user, action="calendar.event_updated", target=event,
                     summary=f"Changed {event.title} ({event.start_date.isoformat()}) on the calendar")
        return Response(self._row(event))

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._check()
        event = self.get_object()
        summary = f"Removed {event.title} ({event.start_date.isoformat()}) from the calendar"
        school = event.school
        event.delete()
        log_activity(school=school, actor=request.user, action="calendar.event_removed", summary=summary)
        return Response(status=204)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def calendar_feed(request):
    """
    GET: the private link to add this calendar to a phone or computer
    calendar app. POST: replace it (the old link stops working).
    """
    if services.viewer(request.user)[0] is None:
        raise PermissionDenied("This account has no school calendar.")
    feed = CalendarFeed.objects.filter(user=request.user).first()
    if request.method == "POST" or feed is None:
        feed, _ = CalendarFeed.objects.update_or_create(user=request.user, defaults={"token": CalendarFeed.new_token()})
    url = request.build_absolute_uri(f"/api/calendar/ical/{feed.token}.ics")
    return Response({"url": url, "webcal": url.replace("https://", "webcal://", 1).replace("http://", "webcal://", 1)})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def calendar_ical(request, token):
    """The calendar as an .ics file, for calendar apps. The long random link is the key."""
    feed = CalendarFeed.objects.filter(token=token).select_related("user").first()
    if feed is None or not feed.user.is_active:
        raise Http404
    school, _ = services.viewer(feed.user)
    if school is None or getattr(getattr(feed.user, "profile", None), "role", "") == "governor":
        raise Http404
    body = services.ical(feed.user, school, request.get_host().split(":")[0])
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="school-calendar.ics"'
    response["Cache-Control"] = "private, max-age=900"
    return response
