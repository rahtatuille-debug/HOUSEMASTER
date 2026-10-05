from django.db.models import Count, Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile, IsSchoolAdmin
from accounts.throttles import InviteIPThrottle, IPThrottle
from activity.services import display_name, log_activity
from gradebook.levels import school_summary
from students.models import SchoolClass, YearGroup

from . import services
from .models import AdmissionsSettings, Application, _token
from .serializers import ApplicationSerializer, ApplyForm, SettingsSerializer


class ApplyThrottle(IPThrottle):
    scope = "admissions_apply"


def _open_settings(token):
    found = AdmissionsSettings.objects.filter(token=token).select_related("school").first()
    if found is None or not found.is_open:
        raise NotFound("This application form isn't open. Please contact the school.")
    return found


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@throttle_classes([InviteIPThrottle])
def apply(request, token):
    """The public form. GET: what the form needs; POST: a family's application."""
    found = _open_settings(token)
    school = found.school
    if request.method == "GET":
        years = found.year_groups.all() if found.year_groups.exists() else YearGroup.objects.filter(school=school)
        summary = school_summary(school)
        return Response({
            "school": {"name": school.name, "motto": school.motto, "email": school.email, "phone": school.phone,
                       "country": summary["country"], "privacy_contact": school.privacy_contact,
                       "has_boarding": school.has_boarding},
            "intro": found.intro,
            "year_groups": [{"id": y.id, "name": y.name} for y in years.order_by("order", "name")],
        })
    if ApplyThrottle().allow_request(request, None) is False:
        return Response({"detail": "Too many applications from here. Please try again later."}, status=429)
    form = ApplyForm(data=request.data, settings=found)
    form.is_valid(raise_exception=True)
    if form.validated_data.get("website"):  # a bot filled the hidden field
        return Response({"reference": "received"}, status=201)
    application = form.save(school=school)
    services.email_family(application, "received")
    log_activity(school=school, actor=None, action="admissions.applied",
                 summary=f"New application for {application.first_name} {application.last_name}")
    return Response({"reference": application.reference}, status=201)


class ApplicationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                         mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Admins: the applications, filtered by ?status=, ?year_group=, ?q=. PATCH moves them on (families are
    emailed at interview, offer, waiting list and decline); POST enrol/ {school_class} enrols."""

    serializer_class = ApplicationSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile, IsSchoolAdmin]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = Application.objects.filter(school=self.request.user.profile.school) \
            .select_related("year_group", "student__school_class")
        params = self.request.query_params
        if status := params.get("status"):
            queryset = queryset.filter(status__in=status.split(","))
        if year := params.get("year_group"):
            queryset = queryset.filter(year_group_id=year)
        for word in (params.get("q") or "").split():
            queryset = queryset.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word) |
                                       Q(parent_name__icontains=word) | Q(parent_email__icontains=word))
        return queryset

    def perform_update(self, serializer):
        before = serializer.instance.status
        after = serializer.validated_data.get("status", before)
        extra = {"decided_by_name": display_name(self.request.user)} if after != before else {}
        application = serializer.save(**extra)
        if after != before:
            log_activity(school=application.school, actor=self.request.user, action="admissions.status",
                         summary=f"{application.first_name} {application.last_name}'s application: "
                                 f"{application.get_status_display().lower()}")
            if after in ("interview", "offered", "waitlist", "declined") and self.request.data.get("tell_family", True):
                services.email_family(application, after)

    def perform_destroy(self, instance):
        log_activity(school=instance.school, actor=self.request.user, action="admissions.deleted",
                     summary=f"Deleted the application for {instance.first_name} {instance.last_name}")
        instance.delete()

    @action(detail=True, methods=["post"])
    def enrol(self, request, pk=None):
        application = self.get_object()
        school_class = SchoolClass.objects.filter(pk=request.data.get("school_class"),
                                                  year_group__school=application.school).first() \
            if str(request.data.get("school_class", "")).isdigit() else None
        if school_class is None:
            raise ValidationError({"school_class": ["Choose a class."]})
        student, sentence = services.enrol(application, school_class, request.user)
        return Response({"message": sentence, "student": student.id,
                         "application": self.get_serializer(application).data})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        counts = dict(Application.objects.filter(school=request.user.profile.school)
                      .values_list("status").annotate(n=Count("id")))
        return Response({"counts": counts, "new": counts.get("new", 0)})


@api_view(["GET", "PATCH", "POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def admissions_settings(request):
    """GET/PATCH {is_open, intro, year_groups}; POST {new_link: true} replaces the link (the old one stops)."""
    found = services.settings_for(request.user.profile.school)
    if request.method == "POST":
        if request.data.get("new_link"):
            found.token = _token()
            found.save(update_fields=["token"])
    elif request.method == "PATCH":
        serializer = SettingsSerializer(found, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(SettingsSerializer(found, context={"request": request}).data)
