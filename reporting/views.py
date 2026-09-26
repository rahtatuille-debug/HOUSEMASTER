from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.permissions import IsSchoolAdmin
from accounts.scoping import check_can_see_student, limit_to_visible_students
from activity.services import log_activity, student_name
from gradebook.locks import check_term_open

from students.models import Student
from gradebook.models import Term
from .models import StudentReport
from .serializers import StudentReportSerializer, GenerateReportSerializer
from .services import generate_report


class StudentReportViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Standard CRUD for StudentReport, plus a `generate` action that calls the
    AI to produce a report from a student's current grades/attendance, and
    the approval steps: `submit` (teacher or admin, from draft), `finalize`
    (admins only; releases it to parents) and `send_back` (admins only;
    back to draft with a `note`). Only draft and submitted reports can be
    edited, and only draft reports can be regenerated.
    """
    queryset = StudentReport.objects.all()
    serializer_class = StudentReportSerializer
    filterset_fields = ["student", "term", "status"]
    school_lookup = "student__school"
    # Only ever actually applied to `generate` (see get_throttles) — the
    # scope name just has to match a key in DEFAULT_THROTTLE_RATES.
    throttle_scope = "ai_report_generation"

    def get_throttles(self):
        if self.action == "generate":
            return [ScopedRateThrottle()]
        return []

    def get_queryset(self):
        return limit_to_visible_students(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        self.check_belongs_to_school(serializer.validated_data["student"].school, "student")
        self.check_belongs_to_school(serializer.validated_data["term"], "term")
        check_term_open(serializer.validated_data["term"])
        check_can_see_student(self.request.user, serializer.validated_data["student"])
        serializer.save()

    def perform_update(self, serializer):
        report = serializer.instance
        if report.status == "finalized":
            raise ValidationError("A finalized report can't be edited. An admin must send it back first.")
        student = serializer.validated_data.get("student", report.student)
        self.check_belongs_to_school(student.school, "student")
        self.check_belongs_to_school(serializer.validated_data.get("term", report.term), "term")
        check_term_open(report.term)
        check_term_open(serializer.validated_data.get("term", report.term))
        check_can_see_student(self.request.user, student)
        report = serializer.save()
        self._log(report, "report.edited", "Edited")

    def perform_destroy(self, instance):
        check_term_open(instance.term)
        if instance.status == "finalized":
            raise ValidationError("A finalized report can't be deleted. An admin must send it back first.")
        self._log(instance, "report.deleted", "Deleted")
        instance.delete()

    def _log(self, report, action, verb, **details):
        log_activity(
            school=report.student.school, actor=self.request.user, action=action, target=report,
            summary=f"{verb} the {report.term.name} report for {student_name(report.student)}", **details,
        )

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        report = self.get_object()
        check_term_open(report.term)
        if report.status != "draft":
            raise ValidationError("Only draft reports can be submitted for approval.")
        report.status = "submitted"
        report.submitted_by = request.user
        report.submitted_at = timezone.now()
        report.save(update_fields=["status", "submitted_by", "submitted_at", "edited_at"])
        self._log(report, "report.submitted", "Submitted for approval")
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"], permission_classes=[IsSchoolAdmin])
    def finalize(self, request, pk=None):
        report = self.get_object()
        check_term_open(report.term)
        if report.status == "finalized":
            raise ValidationError("This report is already finalized.")
        report.status = "finalized"
        report.finalized_by = request.user
        report.finalized_at = timezone.now()
        report.review_note = ""
        report.save(update_fields=["status", "finalized_by", "finalized_at", "review_note", "edited_at"])
        self._log(report, "report.finalized", "Finalized and released to parents")
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"], url_path="send-back", permission_classes=[IsSchoolAdmin])
    def send_back(self, request, pk=None):
        report = self.get_object()
        check_term_open(report.term)
        if report.status == "draft":
            raise ValidationError("This report is already a draft.")
        note = str(request.data.get("note", "")).strip()
        if not note:
            raise ValidationError({"note": "Say what needs changing."})
        was_finalized = report.status == "finalized"
        report.status = "draft"
        report.review_note = note
        report.finalized_by = None
        report.finalized_at = None
        report.save(update_fields=["status", "review_note", "finalized_by", "finalized_at", "edited_at"])
        verb = "Took back from parents and returned" if was_finalized else "Sent back"
        self._log(report, "report.sent_back", verb, note=note)
        return Response(self.get_serializer(report).data)

    @action(detail=False, methods=["post"])
    def generate(self, request):
        input_serializer = GenerateReportSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        # Scoped lookups: a student/term ID from another school 404s here
        # exactly as if it didn't exist, rather than leaking cross-school data.
        caller_school = request.user.profile.school
        try:
            student = Student.objects.get(
                pk=input_serializer.validated_data["student"], school=caller_school
            )
            term = Term.objects.get(
                pk=input_serializer.validated_data["term"], school=caller_school
            )
        except (Student.DoesNotExist, Term.DoesNotExist):
            return Response({"detail": "Student or term not found."}, status=status.HTTP_404_NOT_FOUND)
        check_can_see_student(request.user, student)
        check_term_open(term)
        existing = StudentReport.objects.filter(student=student, term=term).first()
        if existing is not None and existing.status != "draft":
            raise ValidationError(
                "This report has already been submitted or finalized, so it can't be regenerated. "
                "An admin can send it back to draft first."
            )

        try:
            report = generate_report(student, term)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        log_activity(
            school=caller_school, actor=request.user, action="report.generated", target=report,
            summary=f"Generated the {term.name} report for {student_name(student)}",
        )
        return Response(StudentReportSerializer(report).data, status=status.HTTP_200_OK)
