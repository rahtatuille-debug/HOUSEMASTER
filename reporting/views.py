from django.core import signing
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from accounts.mixins import SchoolScopedViewSetMixin
from accounts.permissions import IsSchoolAdmin
from accounts.scoping import check_can_see_student, is_admin, limit_to_visible_students, visible_students
from activity.services import log_activity, student_name
from gradebook.locks import check_term_open

from students.models import SchoolClass, Student
from gradebook.models import Term
from .models import StudentReport
from .serializers import StudentReportSerializer, GenerateReportSerializer
from .services import generate_report

CLASS_RUN_SALT = "reporting.class-run"
CLASS_RUN_MAX_AGE = 6 * 60 * 60  # seconds a class run stays usable


class ClassRunThrottle(ScopedRateThrottle):
    """Limits starting a whole-class run, separately from single reports."""

    def allow_request(self, request, view):
        self.scope = "ai_class_report_generation"
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return SimpleRateThrottle.allow_request(self, request, view)


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
        if self.action == "generate_class":
            # A whole class counts once, against its own (smaller) limit.
            return [ClassRunThrottle()]
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

    # --- Whole-class actions -------------------------------------------------
    # Generating a class is split into steps so no single request runs long:
    # `generate_class` works out who still needs a report and returns a signed
    # run token listing them; the browser then calls `generate_class_next` once
    # per student with that token. Students who already have a report for the
    # term are always skipped, so a teacher's edits are never overwritten.

    def _class_and_term(self, request):
        school = request.user.profile.school
        try:
            school_class = SchoolClass.objects.select_related("year_group").get(
                pk=request.data.get("school_class"), year_group__school=school
            )
        except (SchoolClass.DoesNotExist, ValueError, TypeError):
            raise NotFound("Class not found.")
        try:
            term = Term.objects.get(pk=request.data.get("term"), school=school)
        except (Term.DoesNotExist, ValueError, TypeError):
            raise NotFound("Term not found.")
        if not is_admin(request.user) and not request.user.profile.assignments.filter(
            school_class=school_class
        ).exists():
            raise PermissionDenied("You can only do this for classes you teach.")
        return school_class, term

    def _class_reports(self, request, school_class, term, status):
        return StudentReport.objects.filter(
            student__in=visible_students(request.user).filter(school_class=school_class, is_active=True),
            term=term, status=status,
        )

    @action(detail=False, methods=["post"], url_path="generate-class")
    def generate_class(self, request):
        school_class, term = self._class_and_term(request)
        check_term_open(term)
        students = (visible_students(request.user).filter(school_class=school_class, is_active=True)
                    .order_by("last_name", "first_name"))
        have_report = set(StudentReport.objects.filter(student__in=students, term=term)
                          .values_list("student_id", flat=True))
        todo = [s for s in students if s.id not in have_report]
        run = signing.dumps(
            {"user": request.user.id, "term": term.id, "students": [s.id for s in todo]}, salt=CLASS_RUN_SALT
        )
        if todo:
            log_activity(
                school=school_class.year_group.school, actor=request.user, action="report.class_generated",
                target=school_class,
                summary=f"Started AI reports for {len(todo)} students in {school_class.name}, {term.name}",
            )
        return Response({
            "run": run,
            "students": [{"id": s.id, "name": f"{s.first_name} {s.last_name}"} for s in todo],
            "already_have_reports": len(have_report),
        })

    @action(detail=False, methods=["post"], url_path="generate-class/next")
    def generate_class_next(self, request):
        try:
            run = signing.loads(str(request.data.get("run", "")), salt=CLASS_RUN_SALT, max_age=CLASS_RUN_MAX_AGE)
        except signing.BadSignature:
            raise ValidationError("This class run has expired. Start it again.")
        try:
            student_id = int(request.data.get("student"))
        except (TypeError, ValueError):
            raise ValidationError({"student": "Which student?"})
        if run["user"] != request.user.id or student_id not in run["students"]:
            raise PermissionDenied("That student isn't part of this class run.")

        school = request.user.profile.school
        try:
            student = Student.objects.get(pk=student_id, school=school)
            term = Term.objects.get(pk=run["term"], school=school)
        except (Student.DoesNotExist, Term.DoesNotExist):
            raise NotFound("Student or term not found.")
        check_can_see_student(request.user, student)
        check_term_open(term)
        # Someone may have written this report since the run started.
        existing = StudentReport.objects.filter(student=student, term=term).first()
        if existing is not None:
            return Response({"skipped": True, "report": StudentReportSerializer(existing).data})
        try:
            report = generate_report(student, term)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"skipped": False, "report": StudentReportSerializer(report).data})

    @action(detail=False, methods=["post"], url_path="submit-class")
    def submit_class(self, request):
        school_class, term = self._class_and_term(request)
        check_term_open(term)
        count = self._class_reports(request, school_class, term, "draft").update(
            status="submitted", submitted_by=request.user, submitted_at=timezone.now(), edited_at=timezone.now(),
        )
        if count:
            log_activity(
                school=school_class.year_group.school, actor=request.user, action="report.class_submitted",
                target=school_class,
                summary=f"Submitted {count} {school_class.name} reports for {term.name} for approval",
            )
        return Response({"count": count})

    @action(detail=False, methods=["post"], url_path="finalize-class", permission_classes=[IsSchoolAdmin])
    def finalize_class(self, request):
        # Only reports a teacher has submitted; drafts still need their review.
        school_class, term = self._class_and_term(request)
        check_term_open(term)
        count = self._class_reports(request, school_class, term, "submitted").update(
            status="finalized", finalized_by=request.user, finalized_at=timezone.now(), review_note="",
            edited_at=timezone.now(),
        )
        if count:
            log_activity(
                school=school_class.year_group.school, actor=request.user, action="report.class_finalized",
                target=school_class,
                summary=f"Finalized {count} {school_class.name} reports for {term.name} and released them to parents",
            )
        return Response({"count": count})
