from django.db.models import Count, Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import CanManageAdmissions, HasSchoolProfile
from accounts.throttles import EmailThrottle, InviteIPThrottle, IPThrottle
from activity.services import display_name, log_activity
from gradebook.levels import school_summary
from students.models import SchoolClass, YearGroup

from . import services
from .models import AdmissionsSettings, Application, _token
from .serializers import ApplicationSerializer, ApplyForm, SettingsSerializer


class ApplyThrottle(IPThrottle):
    """Per address: generous, since a school, a cyber cafe or a mobile network can put many families behind one."""
    scope = "admissions_apply"


class ApplyEmailThrottle(EmailThrottle):
    """Per parent email: stricter. Over the limit, the form answers as usual and does nothing (no oracle)."""
    scope = "admissions_apply_email"
    email_field = "parent_email"


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
        return _check_your_email()
    if ApplyEmailThrottle().allow_request(request, None) is False:
        return _check_your_email()
    services.receive(form, found)
    return _check_your_email()


def _check_your_email():
    # The same answer whatever happened, so the form never tells anyone what is on file.
    return Response({"detail": "Thank you. Check your email and confirm your address to send the application."},
                    status=202)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([InviteIPThrottle])
def confirm(request, token):
    """The link in the confirmation email. Single use; expires."""
    from django.db import transaction
    from django.utils import timezone

    with transaction.atomic():
        application = Application.objects.select_for_update().filter(
            confirm_token=services.hash_token(token), confirmed_at__isnull=True,
            confirm_expires_at__gt=timezone.now()).select_related("school").first() if token else None
        if application is None:
            raise ValidationError("This link has expired or has already been used. If you haven't heard from the "
                                  "school, please apply again.")
        application.confirmed_at = timezone.now()
        application.confirm_token = ""
        application.save(update_fields=["confirmed_at", "confirm_token", "updated_at"])
        services.email_family(application, "received")
        log_activity(school=application.school, actor=None, action="admissions.applied",
                     summary=f"New application for {application.first_name} {application.last_name}")
    return Response({"reference": application.reference, "school": application.school.name})


class ApplicationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                         mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Admins and the admissions officer: the applications, filtered by ?status=, ?year_group=, ?q=. PATCH moves them on (families are
    emailed at interview, offer, waiting list and decline); POST enrol/ {school_class} enrols."""

    serializer_class = ApplicationSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile, CanManageAdmissions]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = Application.objects.filter(school=self.request.user.profile.school) \
            .select_related("year_group", "student__school_class")
        params = self.request.query_params
        # Unconfirmed applications are listed only on request (and can be deleted); nothing else touches them.
        if self.action == "list" and params.get("unconfirmed"):
            queryset = queryset.filter(confirmed_at__isnull=True)
        elif self.action != "destroy":
            queryset = queryset.filter(confirmed_at__isnull=False)
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
        student, sentence = services.enrol(application, school_class, request.user,
                                           different_child=request.data.get("different_child") is True)
        return Response({"message": sentence, "student": student.id,
                         "application": self.get_serializer(application).data})

    @action(detail=False, methods=["get"])
    def summary(self, request):
        mine = Application.objects.filter(school=request.user.profile.school)
        counts = dict(mine.filter(confirmed_at__isnull=False).values_list("status").annotate(n=Count("id")))
        return Response({"counts": counts, "new": counts.get("new", 0),
                         "unconfirmed": mine.filter(confirmed_at__isnull=True).count()})


@api_view(["GET", "PATCH", "POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, CanManageAdmissions])
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
