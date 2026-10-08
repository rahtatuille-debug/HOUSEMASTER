from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.permissions import CanManageParents, HasSchoolProfile
from accounts.emails import send_admin_password_reset
from accounts.throttles import InviteIPThrottle, InviteSendRecipientThrottle, InviteSendUserThrottle
from accounts.tokens import tokens_for
from activity.services import log_activity, student_name
from gradebook.levels import school_summary

from clubs.services import parent_view as clubs_parent_view
from discipline.serializers import parent_rows as discipline_parent_rows
from support.services import parent_view as support_parent_view

from . import health_notes
from .invite_emails import send_invite_email
from .models import Guardian, GuardianInvite
from .permissions import IsGuardian
from .serializers import (
    CONTACT_FIELDS,
    AcceptGuardianInviteSerializer,
    GuardianContactSerializer,
    GuardianInvitePreviewSerializer,
    GuardianInviteSerializer,
    GuardianNameSerializer,
    ParentSerializer,
    GuardianStudentSerializer,
    GuardianGradeSerializer,
    GuardianReportSerializer,
)


class GuardianInviteViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """Guardian invites for admins and the school secretary, scoped to the caller's school."""

    queryset = GuardianInvite.objects.all()
    serializer_class = GuardianInviteSerializer
    permission_classes = [HasSchoolProfile, CanManageParents]
    throttle_classes = [InviteSendUserThrottle, InviteSendRecipientThrottle]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def perform_create(self, serializer):
        for student in serializer.validated_data.get("students", []):
            self.check_belongs_to_school(student, "Student")
        invite = serializer.save(school=self.get_school(), invited_by=self.request.user)
        children = ", ".join(student_name(s) for s in invite.students.all())
        log_activity(
            school=invite.school, actor=self.request.user, action="parent_invite.created", target=invite,
            summary=f"Invited parent {invite.name} ({invite.email}) for {children}",
            email=invite.email, students=[s.id for s in invite.students.all()],
        )
        send_invite_email(invite)

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        invite = self.get_object()
        if invite.is_accepted:
            raise ValidationError("This invite has already been accepted.")
        invite.renew()
        send_invite_email(invite)
        log_activity(
            school=invite.school, actor=request.user, action="parent_invite.renewed", target=invite,
            summary=f"Renewed the parent invite for {invite.name} ({invite.email}) with a new link",
        )
        return Response(self.get_serializer(invite).data)

    def perform_destroy(self, instance):
        log_activity(
            school=instance.school, actor=self.request.user, action="parent_invite.cancelled",
            target=instance, summary=f"Cancelled the parent invite for {instance.name} ({instance.email})",
            email=instance.email,
        )
        instance.delete()


class ParentViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Admin-only list of the school's parent accounts. Admins can change
    which children a parent is linked to (PATCH students) and deactivate or
    reactivate the account. Deactivating blocks login straight away but
    keeps the account, its links and its message history.
    """

    queryset = Guardian.objects.select_related("user").prefetch_related("students").order_by(
        "-user__is_active", "display_name"
    )
    serializer_class = ParentSerializer
    permission_classes = [HasSchoolProfile, CanManageParents]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        return Response({"detail": "Use a parent invite to add parents."}, status=405)

    def partial_update(self, request, *args, **kwargs):
        guardian = self.get_object()
        contact = {k: request.data[k] for k in CONTACT_FIELDS + ["admin_note"] if k in request.data}
        if "students" not in request.data and not contact:
            raise ValidationError("Send contact details, or the full list of linked student IDs.")
        if contact:
            self._update_contact(request, guardian, contact)
        if "students" in request.data:
            self._update_students(request, guardian)
        guardian.refresh_from_db()
        return Response(self.get_serializer(guardian).data)

    def _update_contact(self, request, guardian, contact):
        serializer = self.get_serializer(guardian, data=contact, partial=True)
        serializer.is_valid(raise_exception=True)
        changed = [k for k, v in serializer.validated_data.items() if getattr(guardian, k) != v]
        serializer.save()
        if changed:
            labels = [Guardian._meta.get_field(k).verbose_name for k in changed]
            log_activity(
                school=guardian.school, actor=request.user, action="parent.contact_changed", target=guardian,
                summary=f"Updated {guardian.name}'s contact details ({', '.join(labels)})", fields=changed,
            )

    def _update_students(self, request, guardian):
        serializer = self.get_serializer(guardian, data={"students": request.data["students"]}, partial=True)
        serializer.is_valid(raise_exception=True)
        new_students = serializer.validated_data["students"]
        for student in new_students:
            self.check_belongs_to_school(student, "Student")

        before = set(guardian.students.all())
        after = set(new_students)
        guardian.students.set(new_students)
        added, removed = after - before, before - after
        if added or removed:
            parts = []
            if added:
                parts.append("linked " + ", ".join(sorted(student_name(s) for s in added)))
            if removed:
                parts.append("unlinked " + ", ".join(sorted(student_name(s) for s in removed)))
            log_activity(
                school=guardian.school, actor=request.user, action="parent.children_changed",
                target=guardian, summary=f"Changed {guardian.name}'s children: " + "; ".join(parts),
                added=[s.id for s in added], removed=[s.id for s in removed],
            )

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def _set_active(self, request, active):
        guardian = self.get_object()
        if guardian.user.is_active != active:
            guardian.user.is_active = active
            guardian.user.save(update_fields=["is_active"])
            verb = "Reactivated" if active else "Deactivated"
            log_activity(
                school=guardian.school, actor=request.user,
                action="parent.reactivated" if active else "parent.deactivated",
                target=guardian, summary=f"{verb} parent {guardian.name}'s account",
            )
        return Response(self.get_serializer(guardian).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        return self._set_active(request, False)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        return self._set_active(request, True)

    @action(detail=True, methods=["post"], url_path="send-password-reset")
    def send_password_reset(self, request, pk=None):
        guardian = self.get_object()
        if not guardian.user.is_active:
            raise ValidationError("Reactivate this account before sending a password reset.")
        if not guardian.user.email:
            raise ValidationError("This account has no email address to send a reset link to.")
        send_admin_password_reset(guardian.user)
        log_activity(
            school=guardian.school, actor=request.user, action="password.reset_sent", target=guardian,
            summary=f"Sent parent {guardian.name} a password reset email",
        )
        return Response({"detail": f"A password reset link was emailed to {guardian.user.email}."})


class GuardianStudentViewSet(viewsets.ReadOnlyModelViewSet):
    """A guardian's read-only view of the children linked to their account."""

    serializer_class = GuardianStudentSerializer
    permission_classes = [IsAuthenticated, IsGuardian]

    def get_queryset(self):
        return self.request.user.guardian.students.select_related("school_class__year_group").all()

    @action(detail=True, methods=["get"])
    def grades(self, request, pk=None):
        student = self.get_object()
        grades = student.grades.select_related("subject", "term").order_by("-recorded_at")
        if term_id := request.query_params.get("term"):
            grades = grades.filter(term_id=term_id)
        return Response(GuardianGradeSerializer(grades, many=True).data)

    @action(detail=True, methods=["get"])
    def boarding(self, request, pk=None):
        """Boarders only: bed, leave and sick bay visits."""
        from boarding.views import guardian_boarding

        return Response(guardian_boarding(self.get_object()))

    @action(detail=True, methods=["post"], url_path="leave-requests")
    def leave_requests(self, request, pk=None):
        """Ask for leave for a boarder; boarding staff decide."""
        from boarding.views import guardian_request_leave

        return Response(guardian_request_leave(request, self.get_object()), status=201)

    @action(detail=True, methods=["post"], url_path=r"leave-requests/(?P<leave_id>\d+)/cancel")
    def cancel_leave(self, request, pk=None, leave_id=None):
        from boarding.views import guardian_cancel_leave

        return Response(guardian_cancel_leave(request, self.get_object(), leave_id))

    @action(detail=True, methods=["get"])
    def timetable(self, request, pk=None):
        """The child's week: their class's lessons in the subjects they take."""
        from timetable.views import guardian_week

        return Response(guardian_week(self.get_object()))

    @action(detail=True, methods=["get"])
    def profile(self, request, pk=None):
        """
        A parent's view of their own child: details, teachers, attendance and
        the child's own average each term. Class and year-group averages are
        left out (they're built from other children's grades), as are other
        parents' contact details and anything staff-only.
        """
        from students.profile import build_profile

        student = self.get_object()
        full = build_profile(student, request.user)
        return Response({
            "student": GuardianStudentSerializer(student).data,
            "age": full["age"],
            "teachers": full["teachers"],
            "subjects": full["subjects"],
            "attendance": full["attendance"],
            "performance": [{"term": p["term"], "student": p["student"]} for p in full["performance"]],
            # This parent's latest suggestion for the health notes, if any.
            "health_notes_request": health_notes.as_data(health_notes.latest(request.user, student)),
            # Only once a teacher has confirmed it: suggestions stay with staff.
            "support": support_parent_view(student),
            # Only the records staff chose to share, without staff notes.
            "discipline": discipline_parent_rows(student),
            # Clubs and teams: when they meet, attendance, fixtures and results.
            "clubs": clubs_parent_view(student),
        })

    @action(detail=True, methods=["post", "delete"], url_path="health-notes-request")
    def health_notes_request(self, request, pk=None):
        """
        POST {medical_notes, reason?}: suggest new health notes for the school
        to approve (guardians.health_notes). DELETE: withdraw a waiting one.
        """
        student = self.get_object()
        if request.method == "DELETE":
            return Response(health_notes.as_data(health_notes.withdraw(request.user, student)))
        change_request = health_notes.suggest(request.user, student, request.data)
        return Response(health_notes.as_data(change_request), status=201)

    @action(detail=True, methods=["get"])
    def photo(self, request, pk=None):
        from django.http import HttpResponse

        student = self.get_object()
        if not student.photo:
            raise NotFound("No photo.")
        response = HttpResponse(bytes(student.photo), content_type="image/jpeg")
        response["Cache-Control"] = "private, max-age=300"
        return response

    @action(detail=True, methods=["get"])
    def reports(self, request, pk=None):
        student = self.get_object()
        # Draft and submitted reports are internal staff work. Guardians only see
        # a report once the school has explicitly finalized it, and never one
        # with a blank comment (F-11).
        reports = student.reports.filter(status="finalized").with_content().select_related("term").order_by("-generated_at")
        return Response(GuardianReportSerializer(reports, many=True).data)

    @action(detail=True, methods=["get"], url_path="term-summary")
    def term_summary(self, request, pk=None):
        """A child's results for a term, once the school has finalized that term's report."""
        from gradebook.systems import term_summary

        student = self.get_object()
        report = student.reports.filter(status="finalized", term_id=request.query_params.get("term")).with_content().first() \
            if str(request.query_params.get("term", "")).isdigit() else None
        if report is None:
            raise NotFound("There's no finalized report for that term.")
        summary = term_summary(student, report.term, report)
        for row in summary["subjects"]:
            row.pop("subject_id", None)
        return Response(summary)

    @action(detail=True, methods=["get"], url_path="report-card")
    def report_card(self, request, pk=None):
        """The printable report card (PDF) for one finalized term report."""
        from django.http import HttpResponse
        from django.utils.text import slugify

        from reporting.exports import reports_pdf

        student = self.get_object()
        report = student.reports.filter(status="finalized", term_id=request.query_params.get("term")).with_content().first() \
            if str(request.query_params.get("term", "")).isdigit() else None
        if report is None:
            raise NotFound("There's no finalized report for that term.")
        content, _ = reports_pdf(student.school, [student], report.term)
        log_activity(
            school=student.school, actor=request.user, action="report.downloaded", target=report,
            summary=f"{request.user.guardian.name} downloaded the {report.term.name} report card for "
                    f"{student_name(student)}",
        )
        response = HttpResponse(content, content_type="application/pdf")
        filename = f"report-card-{slugify(student.first_name)}-{slugify(student.last_name)}-{slugify(report.term.name)}.pdf"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class GuardianInvitePreviewView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [InviteIPThrottle]

    def get(self, request, token):
        try:
            invite = GuardianInvite.objects.get(token=token)
        except GuardianInvite.DoesNotExist:
            return Response({"detail": "Invite not found."}, status=404)
        return Response(GuardianInvitePreviewSerializer(invite).data)


class AcceptGuardianInviteView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [InviteIPThrottle]

    def post(self, request):
        serializer = AcceptGuardianInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log_activity(
            school=user.guardian.school, actor=user, action="parent_invite.accepted", target=user.guardian,
            summary=f"Parent {user.guardian.name} accepted their invite",
        )
        return Response(tokens_for(user), status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, IsGuardian])
def guardian_me(request):
    guardian = request.user.guardian
    if request.method == "PATCH":
        if "name" in request.data:
            serializer = GuardianNameSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            guardian.display_name = serializer.validated_data["name"]
            guardian.save(update_fields=["display_name"])
        # A parent keeps their own contact details up to date (never the admin note).
        contact = GuardianContactSerializer(
            guardian, data={k: request.data[k] for k in CONTACT_FIELDS + ["email_notifications"] if k in request.data},
            partial=True,
        )
        contact.is_valid(raise_exception=True)
        changed = [k for k, v in contact.validated_data.items() if getattr(guardian, k) != v]
        contact.save()
        if changed:
            log_activity(
                school=guardian.school, actor=request.user, action="parent.contact_changed", target=guardian,
                summary=(f"{guardian.name} turned email notifications {'on' if guardian.email_notifications else 'off'}"
                         if changed == ["email_notifications"] else f"{guardian.name} updated their contact details"),
                fields=changed,
            )
    return Response({
        "id": request.user.id,
        "name": guardian.name,
        "email": request.user.email,
        "contact": GuardianContactSerializer(guardian).data,
        "school": school_summary(guardian.school),
        "students": GuardianStudentSerializer(guardian.students.all(), many=True).data,
    })
