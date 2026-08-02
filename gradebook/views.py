from rest_framework import viewsets

from accounts.mixins import SchoolScopedViewSetMixin

from .models import Subject, Term, Grade
from .serializers import SubjectSerializer, TermSerializer, GradeSerializer


class SubjectViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    school_lookup = "school"

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class TermViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Term.objects.all()
    serializer_class = TermSerializer
    school_lookup = "school"

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class GradeViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Grade.objects.all()
    serializer_class = GradeSerializer
    filterset_fields = ["student", "subject", "term"]
    school_lookup = "student__school"

    def _validate_related(self, validated_data):
        self.check_belongs_to_school(validated_data["student"].school, "student")
        self.check_belongs_to_school(validated_data["subject"].school, "subject")
        self.check_belongs_to_school(validated_data["term"].school, "term")

    def perform_create(self, serializer):
        self._validate_related(serializer.validated_data)
        serializer.save()

    def perform_update(self, serializer):
        student = serializer.validated_data.get("student", serializer.instance.student)
        subject = serializer.validated_data.get("subject", serializer.instance.subject)
        term = serializer.validated_data.get("term", serializer.instance.term)
        self.check_belongs_to_school(student.school, "student")
        self.check_belongs_to_school(subject.school, "subject")
        self.check_belongs_to_school(term.school, "term")
        serializer.save()
