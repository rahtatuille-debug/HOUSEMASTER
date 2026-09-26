from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from django.db.models import Q
from django.utils import timezone

from accounts.permissions import HasSchoolProfile, IsSchoolAdmin
from activity.services import log_activity

from students.models import SchoolClass, YearGroup

from .alerts import alert_recipient_users
from .models import AlertRecipient, Announcement, UrgentAlert
from .permissions import CanViewAnnouncements
from .serializers import (
    AlertRecipientSerializer,
    AnnouncementSerializer,
    GenerateAnnouncementTextSerializer,
    UrgentAlertSerializer,
)
from .services import generate_announcement_text


class AnnouncementViewSet(viewsets.ModelViewSet):
    """Draft, publish and archive one-way administrative announcements."""

    queryset = Announcement.objects.select_related(
        "school", "year_group", "school_class", "created_by"
    )
    serializer_class = AnnouncementSerializer
    filterset_fields = ["audience", "status", "year_group", "school_class"]
    http_method_names = ["get", "post", "patch", "head", "options"]
    throttle_scope = "ai_announcement_drafting"

    def get_throttles(self):
        if self.action == "generate_text":
            return [ScopedRateThrottle()]
        return []

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewAnnouncements()]
        if self.action == "generate_text":
            return [IsAuthenticated(), HasSchoolProfile()]
        return [IsSchoolAdmin()]

    def get_queryset(self):
        if hasattr(self.request.user, "guardian"):
            guardian = self.request.user.guardian
            return super().get_queryset().filter(school=guardian.school).filter(
                Q(status=Announcement.Status.PUBLISHED, audience=Announcement.Audience.ALL_PARENTS)
                | Q(
                    status=Announcement.Status.PUBLISHED,
                    audience=Announcement.Audience.YEAR_GROUP,
                    year_group__classes__students__guardians=guardian,
                )
                | Q(
                    status=Announcement.Status.PUBLISHED,
                    audience=Announcement.Audience.SCHOOL_CLASS,
                    school_class__students__guardians=guardian,
                )
            ).distinct()

        school = self.request.user.profile.school
        queryset = super().get_queryset().filter(school=school)
        if self.request.user.profile.role == "admin":
            return queryset
        # Today, staff membership is the only recipient relationship in the
        # product. Parent and class-targeted announcements remain private to
        # admins until parent accounts/teaching assignments are added.
        return queryset.filter(
            status=Announcement.Status.PUBLISHED,
            audience=Announcement.Audience.ALL_STAFF,
        )

    def _validate_targets(self, serializer):
        school = self.request.user.profile.school
        year_group = serializer.validated_data.get("year_group")
        school_class = serializer.validated_data.get("school_class")
        if year_group and year_group.school_id != school.id:
            raise PermissionDenied("year_group does not belong to your school.")
        if school_class and school_class.year_group.school_id != school.id:
            raise PermissionDenied("school_class does not belong to your school.")

    def perform_create(self, serializer):
        self._validate_targets(serializer)
        announcement = serializer.save(school=self.request.user.profile.school, created_by=self.request.user)
        log_activity(
            school=announcement.school, actor=self.request.user, action="announcement.created",
            target=announcement, summary=f'Drafted the announcement "{announcement.title}"',
        )

    def perform_update(self, serializer):
        if serializer.instance.status != Announcement.Status.DRAFT:
            raise ValidationError("Only draft announcements can be edited.")
        self._validate_targets(serializer)
        serializer.save()

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        announcement = self.get_object()
        if announcement.status != Announcement.Status.DRAFT:
            raise ValidationError("Only draft announcements can be published.")
        announcement.publish()
        log_activity(
            school=announcement.school, actor=request.user, action="announcement.published",
            target=announcement,
            summary=f'Published the announcement "{announcement.title}" to {announcement.get_audience_display().lower()}',
        )
        return Response(self.get_serializer(announcement).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        announcement = self.get_object()
        if announcement.status != Announcement.Status.PUBLISHED:
            raise ValidationError("Only published announcements can be archived.")
        announcement.archive()
        log_activity(
            school=announcement.school, actor=request.user, action="announcement.archived",
            target=announcement, summary=f'Archived the announcement "{announcement.title}"',
        )
        return Response(self.get_serializer(announcement).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="generate-text")
    def generate_text(self, request):
        """Generate editable announcement wording from a staff member's brief.

        This action is deliberately available to both teachers and admins.
        It returns text only; it neither saves nor publishes an announcement.
        """
        input_serializer = GenerateAnnouncementTextSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data
        school = request.user.profile.school
        target_label = None

        if data.get("year_group"):
            try:
                target_label = YearGroup.objects.get(pk=data["year_group"], school=school).name
            except YearGroup.DoesNotExist:
                return Response({"detail": "Year group not found."}, status=status.HTTP_404_NOT_FOUND)
        if data.get("school_class"):
            try:
                school_class = SchoolClass.objects.select_related("year_group").get(
                    pk=data["school_class"], year_group__school=school
                )
                target_label = f"{school_class.year_group.name} — {school_class.name}"
            except SchoolClass.DoesNotExist:
                return Response({"detail": "School class not found."}, status=status.HTTP_404_NOT_FOUND)

        audience_label = Announcement.Audience(data["audience"]).label
        try:
            title, body = generate_announcement_text(
                school=school,
                summary=data["summary"],
                audience_label=audience_label,
                target_label=target_label,
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response({"title": title, "body": body}, status=status.HTTP_200_OK)


class UrgentAlertViewSet(viewsets.ModelViewSet):
    """
    Urgent alerts. Admins can send to any audience; teachers only to the
    parents of a class they teach. Everyone at the school sees alerts sent
    to them; admins see every alert, teachers also see the ones they sent.

    - GET /api/alerts/active/: alerts still waiting for me to tap "I've
      seen this" (drives the red banner).
    - POST /api/alerts/{id}/acknowledge/: "I've seen this".
    - GET /api/alerts/{id}/recipients/: who has and hasn't seen it (sender
      and admins).
    - POST /api/alerts/{id}/end/: end the alert so its banner disappears
      for everyone (sender and admins).
    """

    serializer_class = UrgentAlertSerializer
    permission_classes = [IsAuthenticated, CanViewAnnouncements]
    http_method_names = ["get", "post", "head", "options"]

    def _school(self):
        owner = getattr(self.request.user, "profile", None) or self.request.user.guardian
        return owner.school

    def _is_admin(self):
        profile = getattr(self.request.user, "profile", None)
        return profile is not None and profile.is_admin

    def get_queryset(self):
        alerts = UrgentAlert.objects.filter(school=self._school()).select_related("created_by")
        if self._is_admin():
            return alerts
        return alerts.filter(Q(created_by=self.request.user) | Q(recipients__user=self.request.user)).distinct()

    def _check_can_manage(self, alert):
        if not (self._is_admin() or alert.created_by_id == self.request.user.id):
            raise PermissionDenied("Only the sender or an admin can do this.")

    def perform_create(self, serializer):
        profile = getattr(self.request.user, "profile", None)
        if profile is None:
            raise PermissionDenied("Only staff can send urgent alerts.")
        data = serializer.validated_data
        if not profile.is_admin:
            if data["audience"] != UrgentAlert.Audience.SCHOOL_CLASS:
                raise PermissionDenied("Teachers can only send urgent alerts to the parents of a class they teach.")
            if not profile.assignments.filter(school_class=data["school_class"]).exists():
                raise PermissionDenied("You can only send urgent alerts to classes you teach.")
        alert = UrgentAlert(school=profile.school, created_by=self.request.user, **data)
        users = list(alert_recipient_users(alert))
        if not users:
            raise ValidationError("Nobody with an account would receive this alert.")
        alert.save()
        AlertRecipient.objects.bulk_create([AlertRecipient(alert=alert, user=u) for u in users])
        serializer.instance = alert
        log_activity(
            school=alert.school, actor=self.request.user, action="alert.sent", target=alert,
            summary=f'Sent the urgent alert "{alert.title}" to {len(users)} people '
            f"({alert.get_audience_display().lower()})",
        )

    @action(detail=False, methods=["get"])
    def active(self, request):
        alerts = UrgentAlert.objects.filter(
            school=self._school(), ended_at__isnull=True,
            recipients__user=request.user, recipients__acknowledged_at__isnull=True,
        ).distinct()
        return Response(self.get_serializer(alerts, many=True).data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        updated = alert.recipients.filter(user=request.user, acknowledged_at__isnull=True).update(
            acknowledged_at=timezone.now()
        )
        if not alert.recipients.filter(user=request.user).exists():
            raise ValidationError("This alert wasn't sent to you.")
        if updated:
            log_activity(
                school=alert.school, actor=request.user, action="alert.acknowledged", target=alert,
                summary=f'Saw the urgent alert "{alert.title}"',
            )
        return Response(self.get_serializer(alert).data)

    @action(detail=True, methods=["get"])
    def recipients(self, request, pk=None):
        alert = self.get_object()
        self._check_can_manage(alert)
        rows = alert.recipients.select_related("user__profile", "user__guardian").prefetch_related(
            "user__guardian__students"
        ).order_by("acknowledged_at", "id")
        return Response(AlertRecipientSerializer(rows, many=True).data)

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        alert = self.get_object()
        self._check_can_manage(alert)
        if alert.ended_at is None:
            alert.ended_at = timezone.now()
            alert.save(update_fields=["ended_at"])
            log_activity(
                school=alert.school, actor=request.user, action="alert.ended", target=alert,
                summary=f'Ended the urgent alert "{alert.title}"',
            )
        return Response(self.get_serializer(alert).data)
