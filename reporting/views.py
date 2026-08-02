from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.mixins import SchoolScopedViewSetMixin

from students.models import Student
from gradebook.models import Term
from .models import StudentReport
from .serializers import StudentReportSerializer, GenerateReportSerializer
from .services import generate_report


class StudentReportViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Standard CRUD for StudentReport (e.g. a teacher editing report_comment / status
    before finalizing), plus a `generate` action that calls the AI to produce
    a new report from a student's current grades/attendance.
    """
    queryset = StudentReport.objects.all()
    serializer_class = StudentReportSerializer
    filterset_fields = ["student", "term", "status"]
    school_lookup = "student__school"

    def perform_create(self, serializer):
        self.check_belongs_to_school(serializer.validated_data["student"].school, "student")
        serializer.save()

    def perform_update(self, serializer):
        student = serializer.validated_data.get("student", serializer.instance.student)
        self.check_belongs_to_school(student.school, "student")
        serializer.save()

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

        try:
            report = generate_report(student, term)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(StudentReportSerializer(report).data, status=status.HTTP_200_OK)
