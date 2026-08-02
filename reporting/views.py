from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from students.models import Student
from gradebook.models import Term
from .models import StudentReport
from .serializers import StudentReportSerializer, GenerateReportSerializer
from .services import generate_report


class StudentReportViewSet(viewsets.ModelViewSet):
    """
    Standard CRUD for StudentReport (e.g. a teacher editing report_comment / status
    before finalizing), plus a `generate` action that calls the AI to produce
    a new report from a student's current grades/attendance.
    """
    queryset = StudentReport.objects.all()
    serializer_class = StudentReportSerializer
    filterset_fields = ["student", "term", "status"]

    @action(detail=False, methods=["post"])
    def generate(self, request):
        input_serializer = GenerateReportSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        try:
            student = Student.objects.get(pk=input_serializer.validated_data["student"])
            term = Term.objects.get(pk=input_serializer.validated_data["term"])
        except (Student.DoesNotExist, Term.DoesNotExist):
            return Response({"detail": "Student or term not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            report = generate_report(student, term)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(StudentReportSerializer(report).data, status=status.HTTP_200_OK)
